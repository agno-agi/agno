try:
    from cassio.table.base_table import BaseTable
    from cassio.table.mixins.metadata import MetadataMixin
    from cassio.table.mixins.type_normalizer import TypeNormalizerMixin
    from cassio.table.mixins.vector import VectorMixin

    from .extra_param_mixin import ExtraParamMixin
except (ImportError, ModuleNotFoundError):
    raise ImportError("Could not import cassio python package. Please install it with pip install cassio.")


class AgnoMetadataVectorCassandraTable(ExtraParamMixin, TypeNormalizerMixin, MetadataMixin, VectorMixin, BaseTable):
    pass
