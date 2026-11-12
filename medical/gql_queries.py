import graphene
from core import prefix_filterset, ExtendedConnection, filter_validity
from graphene.utils.deduplicator import deflate
from graphene_django import DjangoObjectType
from program.schema import ProgramGQLType
from .models import Service, ServiceItem, ServiceService


class RowFilteredQuerysetMixin:
    """Hands the rows a medical connection asked for to ``Model.get_queryset`` (OP-2029).

    The diagnoses / medicalItems / medicalServices resolvers no longer filter
    validity themselves: they state what their legacy arguments mean with
    ``legacy_row_filters`` and the connection stores that, under any explicit
    ``isDeleted`` / ``showHistory``, on the request. The model then applies row
    security and the rows.

    Where no rows were stated -- these types are also reached through claim
    items/services, pricelists, reverse relations and node lookups -- the
    queryset is left as it was: those paths never filtered here, and keep not
    doing so (ScopedQuerysetMixin would impose the model's live-only default).
    """

    @classmethod
    def get_queryset(cls, queryset, info):
        from core.gql.row_filter_args import row_filter_kwargs
        model = cls._meta.model
        rows = row_filter_kwargs(model, info)
        if not rows:
            return queryset
        user = getattr(getattr(info, "context", None), "user", None)
        return model.get_queryset(queryset, user, **rows)


class ServiceGQLType(RowFilteredQuerysetMixin, DjangoObjectType):
    attachments_count = graphene.Int()
    client_mutation_id = graphene.String()

    class Meta:
        model = Service
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            'uuid': ['exact'],
            'code': ['exact', 'icontains', 'istartswith'],
            'name': ['exact', 'icontains', 'istartswith'],
            'type': ['exact'],
            'packagetype': ['exact', 'in'],
            'care_type': ['exact'],
            'category': ['exact'],
            'health_facility_id': ['exact'],
            **prefix_filterset("program__", ProgramGQLType._meta.filter_fields)
        }
        connection_class = ExtendedConnection


    # The 26.10 hook re-filtered every query to the current rows, so
    # medicalServices(showHistory: true) lost the history the resolver had asked
    # for. Row security and the rows asked for are now applied by
    # RowFilteredQuerysetMixin -> Service.get_queryset.


class ServiceItemGQLType(DjangoObjectType):
    class Meta:
        model = ServiceItem


class ServiceServiceGQLType(DjangoObjectType):
    class Meta:
        model = ServiceService
