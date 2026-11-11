import graphene
from core import ExtendedConnection
from core.gql import legacy_row_filters, row_filter_arguments
from core.models import Audits, Validity
from core.schema import OrderedDjangoFilterConnectionField
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils.translation import gettext as _
from graphene_django import DjangoObjectType
from medical.gql_mutations import CreateServiceMutation, UpdateServiceMutation, DeleteServiceMutation, \
    CreateItemMutation, UpdateItemMutation, DeleteItemMutation
from .gql_queries import *

from .apps import MedicalConfig
from .models import Diagnosis, Item, Service
import graphene_django_optimizer as gql_optimizer
from .services import check_unique_code_item, check_unique_code_service


class DiagnosisGQLType(RowFilteredQuerysetMixin, DjangoObjectType):
    class Meta:
        model = Diagnosis
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            'id': ['exact'],
            'code': ['exact', 'icontains', 'istartswith'],
            'name': ['exact', 'icontains', 'istartswith'],
        }
        connection_class = ExtendedConnection


class ItemGQLType(RowFilteredQuerysetMixin, DjangoObjectType):
    class Meta:
        model = Item
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            'uuid': ['exact'],
            'code': ['exact', 'icontains', 'istartswith'],
            'name': ['exact', 'icontains', 'istartswith'],
            'package': ['exact', 'icontains', 'istartswith'],
            'type': ['exact'],
            'health_facility_id': ['exact'],
        }
        connection_class = ExtendedConnection


class Query(graphene.ObjectType):
    # OP-3317: every connection below takes isDeleted / showHistory; the resolvers
    # state what their legacy arguments mean (legacy_row_filters) and the model
    # applies it through RowFilteredQuerysetMixin -> Model.get_queryset (OP-2029).
    diagnoses = OrderedDjangoFilterConnectionField(
        DiagnosisGQLType,
        **row_filter_arguments(),
    )
    diagnoses_str = OrderedDjangoFilterConnectionField(
        DiagnosisGQLType,
        str=graphene.String(),
        **row_filter_arguments(),
    )
    medical_items = OrderedDjangoFilterConnectionField(
        ItemGQLType,
        client_mutation_id=graphene.String(),
        orderBy=graphene.List(of_type=graphene.String),
        pricelist_uuid=graphene.UUID(),
        **row_filter_arguments(),
    )
    medical_items_str = OrderedDjangoFilterConnectionField(
        ItemGQLType,
        str=graphene.String(),
        date=graphene.Date(),
        orderBy=graphene.List(of_type=graphene.String),
        pricelist_uuid=graphene.UUID(),
        **row_filter_arguments(),
    )

    medical_services = OrderedDjangoFilterConnectionField(
        ServiceGQLType,
        client_mutation_id=graphene.String(),
        orderBy=graphene.List(of_type=graphene.String),
        pricelist_uuid=graphene.UUID(),
        **row_filter_arguments(),
    )
    medical_services_str = OrderedDjangoFilterConnectionField(
        ServiceGQLType,
        str=graphene.String(),
        date=graphene.Date(),
        orderBy=graphene.List(of_type=graphene.String),
        pricelist_uuid=graphene.UUID(),
        **row_filter_arguments(),
    )
    validate_item_code = graphene.Field(
        graphene.Boolean,
        item_code=graphene.String(required=True),
        description="Checks that the specified item code is unique."
    )
    validate_service_code = graphene.Field(
        graphene.Boolean,
        service_code=graphene.String(required=True),
        description="Checks that the specified service code is unique."
    )

    def resolve_diagnoses_str(self, info, **kwargs):
        # gql_query_diagnosis_perms is [] (open to authenticated users, OMT-281);
        # has_perms([]) is True even for AnonymousUser, so refuse anonymous first
        if info.context.user.is_anonymous or not info.context.user.has_perms(
                MedicalConfig.gql_query_diagnosis_perms):
            raise PermissionDenied(_("unauthorized"))
        # legacy: live diagnoses only
        legacy_row_filters(info, kwargs, validity=Validity.NOW)
        search_str = kwargs.get('str')
        if search_str is not None:
            return Diagnosis.objects \
                .filter(Q(code__icontains=search_str) | Q(name__icontains=search_str))
        else:
            return Diagnosis.objects.all()

    def resolve_diagnoses(self, info, **kwargs):
        # gql_query_diagnosis_perms is [] (open to authenticated users, OMT-281);
        # has_perms([]) is True even for AnonymousUser, so refuse anonymous first
        if info.context.user.is_anonymous or not info.context.user.has_perms(
                MedicalConfig.gql_query_diagnosis_perms):
            raise PermissionDenied(_("unauthorized"))
        # legacy: live diagnoses only
        legacy_row_filters(info, kwargs, validity=Validity.NOW)
        return Diagnosis.objects.all()

    def resolve_medical_items_str(self, info, pricelist_uuid=None, date=None, **kwargs):
        # OMT-281 allow listing of medical services even if the query right is not given
        # if not info.context.user.has_perms(MedicalConfig.gql_query_medical_items_perms):
        if info.context.user.is_anonymous:
            raise PermissionDenied(_("unauthorized"))
        # live items, or those valid on `date` (business validity, history copies
        # included). The legacy filter_validity(date) meant this but passed the date
        # as the argument *name*, so it always returned the live rows.
        legacy_row_filters(
            info, kwargs, validity=Validity.at(date) if date is not None else Validity.NOW)
        search_str = kwargs.get("str")
        health_facility_id = kwargs.get("health_facility_id", None)
        q = Item.objects.all()
        if pricelist_uuid is not None:
            q = q.filter(pricelist_details__items_pricelist__uuid=pricelist_uuid,
                         pricelist_details__validity_to__isnull=True)
        if search_str is not None:
            q = q.filter(Q(code__icontains=search_str) | Q(name__icontains=search_str))
        if health_facility_id is not None:
            q = q.filter(
                Q(health_facility_id=health_facility_id) |
                Q(health_facility_id__isnull=True)
            )
        return q

    def resolve_medical_items(
        self,
        info,
        show_history=False,
        pricelist_uuid=None,
        client_mutation_id=None,
        **kwargs
    ):

        # OMT-281 allow listing of medical services even if the query right is not given
        # if not info.context.user.has_perms(MedicalConfig.gql_query_medical_items_perms):
        if info.context.user.is_anonymous:
            raise PermissionDenied(_("unauthorized"))
        health_facility_id = kwargs.get("health_facility_id", None)
        # legacy: live items; showHistory -> every row (deleted and audit copies),
        # for a user holding the items right only (without it Item.get_queryset
        # gave the live rows). The type hook applies row security and the rows.
        if show_history and info.context.user.has_perms(
                MedicalConfig.gql_query_medical_items_perms):
            legacy_row_filters(info, kwargs, validity=Validity.ALL, audits=Audits.ALL)
        else:
            legacy_row_filters(info, kwargs, validity=Validity.NOW)
        queryset = Item.objects.all()
        if pricelist_uuid is not None:
            queryset = queryset.filter(
                pricelist_details__items_pricelist__uuid=pricelist_uuid
            )
        if client_mutation_id:
            queryset = queryset.filter(
                mutations__mutation__client_mutation_id=client_mutation_id
            )
        if health_facility_id is not None:
            queryset = queryset.filter(
                Q(health_facility_id=health_facility_id) |
                Q(health_facility_id__isnull=True)
            )
        return gql_optimizer.query(queryset, info)

    def resolve_medical_services_str(
        self, info, pricelist_uuid=None, date=None, **kwargs
    ):
        # OMT-281 allow listing of medical services even if the query right is not given
        # if not info.context.user.has_perms(MedicalConfig.gql_query_medical_services_perms):
        if info.context.user.is_anonymous:
            raise PermissionDenied(_("unauthorized"))
        # live services, or those valid on `date` (business validity, history copies
        # included). The legacy filter_validity(date) meant this but passed the date
        # as the argument *name*, so it always returned the live rows.
        legacy_row_filters(
            info, kwargs, validity=Validity.at(date) if date is not None else Validity.NOW)
        search_str = kwargs.get("str")
        health_facility_id = kwargs.get("health_facility_id", None)
        q = Service.objects.all()
        if pricelist_uuid is not None:
            q = q.filter(pricelist_details__services_pricelist__uuid=pricelist_uuid,
                         pricelist_details__validity_to__isnull=True)
        if search_str is not None:
            q = q.filter(Q(code__icontains=search_str) | Q(name__icontains=search_str))
        if health_facility_id is not None:
            q = q.filter(
                Q(health_facility_id=health_facility_id) |
                Q(health_facility_id__isnull=True)
            )
        return q

    def resolve_medical_services(
        self,
        info,
        show_history=False,
        pricelist_uuid=None,
        client_mutation_id=None,
        **kwargs
    ):
        # OMT-281 allow listing of medical services even if the query right is not given
        # if not info.context.user.has_perms(MedicalConfig.gql_query_medical_services_perms):
        if info.context.user.is_anonymous:
            raise PermissionDenied(_("unauthorized"))
        health_facility_id = kwargs.get("health_facility_id", None)
        # legacy: live services; showHistory -> every row (deleted and audit copies),
        # for a user holding the services right only (without it Service.get_queryset
        # gave the live rows). The type hook applies row security and the rows.
        if show_history and info.context.user.has_perms(
                MedicalConfig.gql_query_medical_services_perms):
            legacy_row_filters(info, kwargs, validity=Validity.ALL, audits=Audits.ALL)
        else:
            legacy_row_filters(info, kwargs, validity=Validity.NOW)
        queryset = Service.objects.all()
        if pricelist_uuid is not None:
            queryset = queryset.filter(
                pricelist_details__services_pricelist__uuid=pricelist_uuid
            )
        if client_mutation_id:
            queryset = queryset.filter(
                mutations__mutation__client_mutation_id=client_mutation_id
            )
        if health_facility_id is not None:
            queryset = queryset.filter(
                Q(health_facility_id=health_facility_id) |
                Q(health_facility_id__isnull=True)
            )
        return gql_optimizer.query(queryset, info)

    def resolve_validate_service_code(self, info, **kwargs):
        if not info.context.user.has_perms(MedicalConfig.gql_query_medical_services_perms):
            raise PermissionDenied(_("unauthorized"))
        errors = check_unique_code_service(code=kwargs['service_code'])
        return False if errors else True

    def resolve_validate_item_code(self, info, **kwargs):
        if not info.context.user.has_perms(MedicalConfig.gql_query_medical_items_perms):
            raise PermissionDenied(_("unauthorized"))
        errors = check_unique_code_item(code=kwargs['item_code'])
        return False if errors else True


class Mutation(graphene.ObjectType):
    create_service = CreateServiceMutation.Field()
    update_service = UpdateServiceMutation.Field()
    delete_service = DeleteServiceMutation.Field()
    create_item = CreateItemMutation.Field()
    update_item = UpdateItemMutation.Field()
    delete_item = DeleteItemMutation.Field()
