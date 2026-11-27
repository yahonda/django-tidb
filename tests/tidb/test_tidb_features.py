from django.db import IntegrityError, connection
from django.test import TransactionTestCase


class TiDBCheckConstraintFeatureTests(TransactionTestCase):
    available_apps = []

    def tidb_enforces_check_constraints(self):
        table = connection.ops.quote_name("tidb_check_constraint_probe")
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE %s (n integer CHECK (n >= 0))" % table)
            try:
                cursor.execute("INSERT INTO %s (n) VALUES (-1)" % table)
            except IntegrityError:
                return True
            else:
                return False
            finally:
                cursor.execute("DROP TABLE %s" % table)

    def test_supports_check_constraints(self):
        # The features must match whether the server enforces CHECK
        # constraints, which depends on the TiDB version and on
        # tidb_enable_check_constraint.
        enforced = self.tidb_enforces_check_constraints()
        self.assertIs(connection.features.supports_column_check_constraints, enforced)
        self.assertIs(connection.features.supports_table_check_constraints, enforced)
