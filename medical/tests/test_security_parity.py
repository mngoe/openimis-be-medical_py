"""
Security parity tests for medical (API rights) against the openimis-dev-tools reference
(medical/medical/tests_api.py, tests_rights_roles.py, release/26.10).

Medical items/services/diagnoses are reference data: no row scope in the reference either.
The reference contract is: anonymous refused everywhere; diagnoses / validate*Code need the
right; medicalItems / medicalServices readable by any AUTHENTICATED user (OMT-281);
mutations need their right.
Each test asserts the REFERENCE behaviour: a FAIL is a gap in the Cameroon code.
Tags: [REF <file>::<test>] ported, [NEW] no reference equivalent.
"""
import json

from django.core.cache import cache
from django.core.exceptions import PermissionDenied

from core.models.openimis_graphql_test_case import openIMISGraphQLTestCase
from core.test_helpers import create_right_only_user, get_test_token, perm_ids
from medical.apps import MedicalConfig
from medical.models import Item, Service
from medical.test_helpers import create_test_item, create_test_service

ITEMS_QUERY = 'query { medicalItems(first: 5) { edges { node { id code } } } }'
SERVICES_QUERY = 'query { medicalServices(first: 5) { edges { node { id code } } } }'
DIAGNOSES_QUERY = 'query { diagnoses(first: 5) { edges { node { id code } } } }'
VALIDATE_ITEM = 'query { validateItemCode(itemCode: "NO-SUCH-ITEM") }'
VALIDATE_SERVICE = 'query { validateServiceCode(serviceCode: "NO-SUCH-SVC") }'


class MedicalSecurityParityTests(openIMISGraphQLTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.item = create_test_item("D", custom_props={"code": "SPMI1"})
        cls.service = create_test_service("A", custom_props={"code": "SPMS1"})
        cls.no_right = create_right_only_user("spmnoright", [])
        cls.items_user = create_right_only_user(
            "spmitems", perm_ids(MedicalConfig.gql_query_medical_items_perms))
        cls.services_user = create_right_only_user(
            "spmservices", perm_ids(MedicalConfig.gql_query_medical_services_perms))
        cls.diag_user = create_right_only_user(
            "spmdiag", perm_ids(MedicalConfig.gql_query_diagnosis_perms))

    def setUp(self):
        cache.clear()

    def _gql(self, user, query):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {get_test_token(user)}"} if user else {}
        return json.loads(self.query(query, headers=headers).content)

    def _ok(self, content):
        return not content.get("errors")

    # ---------------------------------------------------------------- anonymous
    def test_no_auth_items_query(self):
        """[REF tests_api.py::test_no_auth_items_query]"""
        self.assertFalse(self._ok(self._gql(None, ITEMS_QUERY)))

    def test_no_auth_services_query(self):
        """[REF tests_api.py::test_no_auth_services_query]"""
        self.assertFalse(self._ok(self._gql(None, SERVICES_QUERY)))

    def test_no_auth_diagnoses_query(self):
        """[REF medical/schema.py:103 resolve_diagnoses is_anonymous guard] anonymous
        diagnoses / diagnosesStr refused (Cameroon relies on has_perms([]) == True)."""
        self.assertFalse(self._ok(self._gql(None, DIAGNOSES_QUERY)), "diagnoses open to anonymous")
        self.assertFalse(self._ok(self._gql(None, 'query { diagnosesStr(first: 5) { edges { node { code } } } }')),
                         "diagnosesStr open to anonymous")

    # ---------------------------------------------------------------- rights
    def test_query_medical_items_right(self):
        """[REF tests_rights_roles.py::MedicalRightsTests::test_query_medical_items_right]"""
        self.assertTrue(self._ok(self._gql(self.items_user, VALIDATE_ITEM)))
        self.assertFalse(self._ok(self._gql(self.no_right, VALIDATE_ITEM)))
        self.assertTrue(self._ok(self._gql(self.items_user, ITEMS_QUERY)))

    def test_query_medical_services_right(self):
        """[REF tests_rights_roles.py::MedicalRightsTests::test_query_medical_services_right]"""
        self.assertTrue(self._ok(self._gql(self.services_user, VALIDATE_SERVICE)))
        self.assertFalse(self._ok(self._gql(self.no_right, VALIDATE_SERVICE)))
        self.assertTrue(self._ok(self._gql(self.services_user, SERVICES_QUERY)))

    def test_diagnoses_authenticated_read(self):
        """[REF medical/schema.py resolve_diagnoses] gql_query_diagnosis_perms is [] in the
        reference too, so any authenticated user reads diagnoses (shared weakness: an
        empty right list means 'everyone')."""
        self.assertTrue(self._ok(self._gql(self.diag_user, DIAGNOSES_QUERY)))
        self.assertTrue(self._ok(self._gql(self.no_right, DIAGNOSES_QUERY)))

    def test_authenticated_reads_items_services(self):
        """[REF tests_api.py::test_no_right_items_query / OMT-281] catalogue readable by any
        authenticated user (kept open in the reference)."""
        self.assertTrue(self._ok(self._gql(self.no_right, ITEMS_QUERY)))
        self.assertTrue(self._ok(self._gql(self.no_right, SERVICES_QUERY)))

    # ---------------------------------------------------------------- mutations
    def test_create_item_requires_right(self):
        """[REF medical gql_mutations has_perms]"""
        from medical.gql_mutations import CreateItemMutation
        CreateItemMutation.async_mutate(
            self.no_right, code="SPMNEW", name="x", type="D", care_type="B", price=1,
            patient_category=15, program=1)
        self.assertFalse(Item.objects.filter(code="SPMNEW").exists())

    def test_update_item_requires_right(self):
        """[REF medical gql_mutations has_perms]"""
        from medical.gql_mutations import UpdateItemMutation
        UpdateItemMutation.async_mutate(
            self.no_right, uuid=str(self.item.uuid), code="SPMI1", name="HACKED", type="D",
            care_type="B", price=1, patient_category=15, program=self.item.program_id)
        self.assertNotEqual(Item.objects.get(id=self.item.id).name, "HACKED")

    def test_delete_item_requires_right(self):
        """[REF medical gql_mutations has_perms]"""
        from medical.gql_mutations import DeleteItemMutation
        with self.assertRaises(PermissionDenied):
            DeleteItemMutation.async_mutate(self.no_right, uuids=[str(self.item.uuid)])

    def test_delete_service_requires_right(self):
        """[REF medical gql_mutations has_perms]"""
        from medical.gql_mutations import DeleteServiceMutation
        with self.assertRaises(PermissionDenied):
            DeleteServiceMutation.async_mutate(self.no_right, uuids=[str(self.service.uuid)])
        self.assertTrue(Service.objects.filter(id=self.service.id, validity_to__isnull=True).exists())
