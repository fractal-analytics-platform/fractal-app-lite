from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from fractal_lite._dataset import Dataset, ZarrUrl


class BaseFilter(BaseModel):
    def run(self, dataset: Dataset) -> Dataset:
        raise NotImplementedError(
            "BaseFilter is an abstract class and cannot be run directly."
        )

    def _deactivate_where(
        self, dataset: Dataset, keep: Callable[[ZarrUrl], bool]
    ) -> Dataset:
        """Deactivate every image for which keep is false, leaving the rest as-is."""
        new_urls = [
            zu if keep(zu) else zu.model_copy(update={"active": False})
            for zu in dataset.zarr_urls
        ]
        return dataset.model_copy(update={"zarr_urls": new_urls})


class AttributeFilter(BaseFilter):
    type: Literal["attribute"] = "attribute"
    attribute: str
    value: str

    def run(self, dataset: Dataset) -> Dataset:
        # Attributes can be any type, so coerce to str before comparing.
        return self._deactivate_where(
            dataset, lambda zu: str(zu.attributes.get(self.attribute)) == self.value
        )


class TypeFilter(BaseFilter):
    type: Literal["type"] = "type"
    key: str
    value: bool

    def run(self, dataset: Dataset) -> Dataset:
        # Types are booleans, so compare directly (no string coercion).
        return self._deactivate_where(
            dataset, lambda zu: zu.types.get(self.key) == self.value
        )


# Discriminated union of concrete filters, so workflow steps round-trip to/from
# JSON without collapsing to the abstract ``BaseFilter``.
Filter = Annotated[AttributeFilter | TypeFilter, Field(discriminator="type")]
