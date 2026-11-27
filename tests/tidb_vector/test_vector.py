import numpy as np
from math import sqrt
from django.db import connection, models
from django.db.utils import OperationalError
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext, isolate_apps
from django_tidb.fields.vector import (
    CosineDistance,
    L1Distance,
    L2Distance,
    NegativeInnerProduct,
    VectorField,
    VectorIndex,
)

from .models import Document, DocumentExplicitDimension, DocumentWithAnnIndex


class TiDBVectorFieldTests(TestCase):
    model = Document

    def test_create_get(self):
        obj = self.model.objects.create(
            content="test content",
            embedding=[1, 2, 3],
        )
        obj = self.model.objects.get(pk=obj.pk)
        self.assertTrue(np.array_equal(obj.embedding, np.array([1, 2, 3])))
        self.assertEqual(obj.embedding.dtype, np.float32)

    def test_get_with_different_dimension(self):
        self.model.objects.create(
            content="test content",
            embedding=[1, 2, 3],
        )
        with self.assertRaises(OperationalError) as cm:
            list(
                self.model.objects.annotate(
                    distance=CosineDistance("embedding", [3, 1, 2, 4])
                ).values_list("distance", flat=True)
            )
        self.assertIn("vectors have different dimensions", str(cm.exception))

    def create_documents(self):
        vectors = [[1, 1, 1], [2, 2, 2], [1, 1, 2]]
        for i, v in enumerate(vectors):
            self.model.objects.create(
                content=f"{i + 1}",
                embedding=v,
            )

    def test_l1_distance(self):
        self.create_documents()
        distance = L1Distance("embedding", [1, 1, 1])
        docs = self.model.objects.annotate(distance=distance).order_by("distance")
        self.assertEqual([d.content for d in docs], ["1", "3", "2"])
        self.assertEqual([d.distance for d in docs], [0, 1, 3])

    def test_l2_distance(self):
        self.create_documents()
        distance = L2Distance("embedding", [1, 1, 1])
        docs = self.model.objects.annotate(distance=distance).order_by("distance")
        self.assertEqual([d.content for d in docs], ["1", "3", "2"])
        self.assertEqual([d.distance for d in docs], [0, 1, sqrt(3)])

    def test_cosine_distance(self):
        self.create_documents()
        distance = CosineDistance("embedding", [1, 1, 1])
        docs = self.model.objects.annotate(distance=distance).order_by("distance")
        self.assertEqual([d.content for d in docs], ["1", "2", "3"])
        self.assertEqual([d.distance for d in docs], [0, 0, 0.05719095841793653])

    def test_negative_inner_product(self):
        self.create_documents()
        distance = NegativeInnerProduct("embedding", [1, 1, 1])
        docs = self.model.objects.annotate(distance=distance).order_by("distance")
        self.assertEqual([d.content for d in docs], ["2", "3", "1"])
        self.assertEqual([d.distance for d in docs], [-6, -4, -3])


class TiDBVectorFieldExplicitDimensionTests(TiDBVectorFieldTests):
    model = DocumentExplicitDimension


class TiDBVectorFieldWithAnnIndexTests(TiDBVectorFieldTests):
    model = DocumentWithAnnIndex


@isolate_apps("tidb_vector")
class VectorIndexSchemaTests(TransactionTestCase):
    available_apps = []

    def setUp(self):
        class VectorIndexDocument(models.Model):
            embedding = VectorField(dimensions=3)

            class Meta:
                app_label = "tidb_vector"

        self.model = VectorIndexDocument
        self.index = VectorIndex(CosineDistance("embedding"), name="idx_cos")

    def tearDown(self):
        with connection.schema_editor() as editor:
            editor.delete_model(self.model)

    def get_tiflash_replica_count(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT replica_count FROM information_schema.tiflash_replica
                WHERE table_schema = DATABASE() AND table_name = %s
                """,
                [self.model._meta.db_table],
            )
            row = cursor.fetchone()
        return row[0] if row else None

    def get_index_names(self):
        with connection.cursor() as cursor:
            return set(
                connection.introspection.get_constraints(
                    cursor, self.model._meta.db_table
                )
            )

    def set_tiflash_replica_queries(self, queries):
        return [q["sql"] for q in queries if "SET TIFLASH REPLICA" in q["sql"]]

    def test_create_sql_is_single_statement(self):
        with connection.schema_editor() as editor:
            editor.create_model(self.model)
            sql = str(self.index.create_sql(self.model, editor))
        self.assertTrue(sql.startswith("CREATE VECTOR INDEX"), sql)
        self.assertNotIn(";", sql)

    def test_create_model_sets_tiflash_replica(self):
        self.model._meta.indexes = [self.index]
        with CaptureQueriesContext(connection) as ctx:
            with connection.schema_editor() as editor:
                editor.create_model(self.model)
        self.assertEqual(len(self.set_tiflash_replica_queries(ctx.captured_queries)), 1)
        self.assertEqual(self.get_tiflash_replica_count(), 1)
        self.assertIn("idx_cos", self.get_index_names())

    def test_add_index_sets_tiflash_replica(self):
        with connection.schema_editor() as editor:
            editor.create_model(self.model)
        self.assertIsNone(self.get_tiflash_replica_count())
        with CaptureQueriesContext(connection) as ctx:
            with connection.schema_editor() as editor:
                editor.add_index(self.model, self.index)
        self.assertEqual(len(self.set_tiflash_replica_queries(ctx.captured_queries)), 1)
        self.assertEqual(self.get_tiflash_replica_count(), 1)
        self.assertIn("idx_cos", self.get_index_names())

    def test_add_index_keeps_tiflash_replica(self):
        with connection.schema_editor() as editor:
            editor.create_model(self.model)
            editor.execute(
                "ALTER TABLE %s SET TIFLASH REPLICA 1"
                % editor.quote_name(self.model._meta.db_table)
            )
        with CaptureQueriesContext(connection) as ctx:
            with connection.schema_editor() as editor:
                editor.add_index(self.model, self.index)
        self.assertEqual(self.set_tiflash_replica_queries(ctx.captured_queries), [])
        self.assertIn("idx_cos", self.get_index_names())
