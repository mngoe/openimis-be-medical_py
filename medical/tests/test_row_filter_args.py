"""diagnoses / medicalItems / medicalServices (and their *Str variants): the legacy
arguments keep their meaning, isDeleted / showHistory are new (OP-3317).

Validity is applied by the models (OP-2029), not by the resolvers: the resolvers
only state what their legacy arguments mean (legacy_row_filters).

One code per model with three rows: the live row, an audit copy of it
(save_history: legacy_id set) and a deleted row (validity_to set, no legacy_id).
"""
import json
from dataclasses import dataclass

from graphql_jwt.shortcuts import get_token
from graphql_relay import to_global_id

from core.models import User
from core.models.openimis_graphql_test_case import openIMISGraphQLTestCase
from core.test_helpers import create_test_interactive_user, create_test_role, mark_deleted
from medical.models import Diagnosis
from medical.test_helpers import create_test_item, create_test_service


@dataclass
class DummyContext:
    user: User


class MedicalRowFilterArgsTest(openIMISGraphQLTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = create_test_interactive_user(username="medRowArgsAdmin")
        cls.token = get_token(cls.admin, DummyContext(user=cls.admin))
        no_right = create_test_interactive_user(
            username="medRowArgsNoRight", roles=[create_test_role(name="medRowArgs-no-right").id])
        cls.no_right_token = get_token(no_right, DummyContext(user=no_right))

        # the deleted row first: create_test_* reuse a live row with the same code
        deleted = create_test_item("D", custom_props={"code": "RFAI"})
        mark_deleted(deleted)
        live = create_test_item("D", custom_props={"code": "RFAI"})
        cls.item = cls._rows("ItemGQLType", live, live.save_history(), deleted)

        deleted = create_test_service("C", custom_props={"code": "RFAS"})
        mark_deleted(deleted)
        live = create_test_service("C", custom_props={"code": "RFAS"})
        cls.service = cls._rows("ServiceGQLType", live, live.save_history(), deleted)

        deleted = Diagnosis.objects.create(code="RFAD", name="row args deleted", audit_user_id=-1)
        mark_deleted(deleted)
        live = Diagnosis.objects.create(code="RFAD", name="row args live", audit_user_id=-1)
        cls.diagnosis = cls._rows("DiagnosisGQLType", live, live.save_history(), deleted)

    @staticmethod
    def _rows(type_name, live, copy_id, deleted):
        return {
            "live": to_global_id(type_name, live.id),
            "copy": to_global_id(type_name, copy_id),
            "deleted": to_global_id(type_name, deleted.id),
        }

    def _ids(self, field, args, token=None):
        response = self.query(
            '{ %s(%s) { edges { node { id } } } }' % (field, args),
            headers={"HTTP_AUTHORIZATION": f"Bearer {token or self.token}"})
        self.assertResponseNoErrors(response)
        edges = json.loads(response.content)["data"][field]["edges"]
        return {e["node"]["id"] for e in edges}

    def _expect(self, rows, *names):
        return {rows[name] for name in names}

    # -- medicalItems / medicalServices: live; showHistory -> every row ------------

    def test_items_and_services_default_to_live_rows(self):
        for field, code, rows in (("medicalItems", "RFAI", self.item),
                                  ("medicalServices", "RFAS", self.service)):
            with self.subTest(field):
                self.assertEqual(self._expect(rows, "live"), self._ids(field, f'code: "{code}"'))

    def test_items_and_services_show_history_is_every_row(self):
        for field, code, rows in (("medicalItems", "RFAI", self.item),
                                  ("medicalServices", "RFAS", self.service)):
            with self.subTest(field):
                self.assertEqual(self._expect(rows, "live", "copy", "deleted"),
                                 self._ids(field, f'code: "{code}", showHistory: true'))

    def test_items_and_services_show_history_needs_the_right(self):
        for field, code, rows in (("medicalItems", "RFAI", self.item),
                                  ("medicalServices", "RFAS", self.service)):
            with self.subTest(field):
                self.assertEqual(
                    self._expect(rows, "live"),
                    self._ids(field, f'code: "{code}", showHistory: true', self.no_right_token))

    def test_items_and_services_is_deleted(self):
        for field, code, rows in (("medicalItems", "RFAI", self.item),
                                  ("medicalServices", "RFAS", self.service)):
            with self.subTest(field):
                self.assertEqual(self._expect(rows, "deleted"),
                                 self._ids(field, f'code: "{code}", isDeleted: true'))
                self.assertEqual(self._expect(rows, "live"),
                                 self._ids(field, f'code: "{code}", isDeleted: false'))
                self.assertEqual(self._expect(rows, "live", "copy"),
                                 self._ids(field, f'code: "{code}", isDeleted: false, showHistory: true'))

    # -- medicalItemsStr / medicalServicesStr: live -------------------------------

    def test_str_variants(self):
        for field, code, rows in (("medicalItemsStr", "RFAI", self.item),
                                  ("medicalServicesStr", "RFAS", self.service)):
            with self.subTest(field):
                self.assertEqual(self._expect(rows, "live"), self._ids(field, f'str: "{code}"'))
                self.assertEqual(self._expect(rows, "deleted"),
                                 self._ids(field, f'str: "{code}", isDeleted: true'))
                self.assertEqual(self._expect(rows, "live", "copy"),
                                 self._ids(field, f'str: "{code}", showHistory: true'))

    def test_str_variants_date_is_the_business_validity(self):
        """`date` returns the version valid that day, whether live, a history copy or deleted."""
        from graphql_relay import from_global_id
        from medical.models import Item, Service
        periods = {
            "deleted": ("2019-01-01", "2019-12-31"),
            "copy": ("2020-01-01", "2020-12-31"),
            "live": ("2021-01-01", None),
        }
        for field, code, rows, model in (("medicalItemsStr", "RFAI", self.item, Item),
                                         ("medicalServicesStr", "RFAS", self.service, Service)):
            for name, (valid_from, valid_to) in periods.items():
                model.objects.filter(id=from_global_id(rows[name])[1]).update(
                    validity_from=valid_from, validity_to=valid_to)
            with self.subTest(field):
                for day, expected in (("2019-06-01", "deleted"), ("2020-06-01", "copy"),
                                      ("2022-06-01", "live")):
                    self.assertEqual(self._expect(rows, expected),
                                     self._ids(field, f'str: "{code}", date: "{day}"'), day)
                self.assertEqual(set(), self._ids(field, f'str: "{code}", date: "2000-01-01"'))

    # -- diagnoses / diagnosesStr: live -------------------------------------------

    def test_diagnoses(self):
        for field, arg in (("diagnoses", 'code: "RFAD"'), ("diagnosesStr", 'str: "RFAD"')):
            with self.subTest(field):
                self.assertEqual(self._expect(self.diagnosis, "live"), self._ids(field, arg))
                self.assertEqual(self._expect(self.diagnosis, "deleted"),
                                 self._ids(field, f'{arg}, isDeleted: true'))
                self.assertEqual(self._expect(self.diagnosis, "live"),
                                 self._ids(field, f'{arg}, isDeleted: false'))
                self.assertEqual(self._expect(self.diagnosis, "live", "copy"),
                                 self._ids(field, f'{arg}, showHistory: true'))
