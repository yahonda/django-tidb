# Copyright 2021 PingCAP, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# See the License for the specific language governing permissions and
# limitations under the License.

from django.db.backends.ddl_references import Statement, Table
from django.db.backends.mysql.schema import (
    DatabaseSchemaEditor as MysqlDatabaseSchemaEditor,
)


class DatabaseSchemaEditor(MysqlDatabaseSchemaEditor):
    # Unsupported add column and foreign key in single statement
    # https://github.com/pingcap/tidb/issues/45474
    sql_create_column_inline_fk = None

    sql_set_tiflash_replica = "ALTER TABLE %(table)s SET TIFLASH REPLICA 1"

    @property
    def sql_delete_check(self):
        return "ALTER TABLE %(table)s DROP CHECK %(name)s"

    @property
    def sql_rename_column(self):
        return "ALTER TABLE %(table)s CHANGE %(old_column)s %(new_column)s %(type)s"

    def skip_default_on_alter(self, field):
        if self._is_limited_data_type(field):
            # TiDB doesn't support defaults for BLOB/TEXT/JSON in the
            # ALTER COLUMN statement.
            return True
        return False

    @property
    def _supports_limited_data_type_defaults(self):
        return False

    def _field_should_be_indexed(self, model, field):
        if not field.db_index or field.unique:
            return False
        # No need to create an index for ForeignKey fields except if
        # db_constraint=False because the index from that constraint won't be
        # created.
        if field.get_internal_type() == "ForeignKey" and field.db_constraint:
            return False
        return not self._is_limited_data_type(field)

    def add_field(self, model, field):
        if field._unique:
            # TiDB does not support multiple operations with a single DDL statement,
            # so we need to execute the unique constraint creation separately.
            field._unique = False
            # Django set `cached_property` decorator for `unique` property,
            # so we need to clear the cached value.
            if "unique" in field.__dict__:
                del field.unique
            super().add_field(model, field)
            field._unique = True
            if "unique" in field.__dict__:
                del field.unique
            self.execute(self._create_unique_sql(model, [field]))
        else:
            super().add_field(model, field)

    def _set_tiflash_replica_sql(self, model):
        return Statement(
            self.sql_set_tiflash_replica,
            table=Table(model._meta.db_table, self.quote_name),
        )

    def _has_tiflash_replica(self, model):
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1 FROM information_schema.tiflash_replica
                WHERE table_schema = DATABASE() AND table_name = %s
                    AND replica_count > 0
                """,
                [model._meta.db_table],
            )
            return cursor.fetchone() is not None

    def _model_indexes_sql(self, model):
        output = super()._model_indexes_sql(model)
        # TiDB can't create a vector index on a table without a TiFlash
        # replica. The table has just been created, so it has none.
        if output and any(
            getattr(index, "requires_tiflash_replica", False)
            for index in model._meta.indexes
        ):
            output.insert(0, self._set_tiflash_replica_sql(model))
        return output

    def add_index(self, model, index):
        # Don't change the TiFlash replica count of a table that already has a
        # TiFlash replica.
        if getattr(
            index, "requires_tiflash_replica", False
        ) and not self._has_tiflash_replica(model):
            self.execute(self._set_tiflash_replica_sql(model))
        super().add_index(model, index)

    def table_sql(self, model):
        sql, params = super().table_sql(model)
        tidb_auto_id_cache = getattr(model._meta, "tidb_auto_id_cache", None)
        if tidb_auto_id_cache is not None:
            sql += " AUTO_ID_CACHE %s" % tidb_auto_id_cache
        return sql, params
