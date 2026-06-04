from typing import Annotated, Literal

from pydantic import BaseModel, Field

from fractal_lite._dataset import Dataset


class BaseFilter(BaseModel):
    def run(self, dataset: Dataset) -> Dataset:
        raise NotImplementedError(
            "BaseFilter is an abstract class and cannot be run directly."
        )


class AttributeFilter(BaseFilter):
    type: Literal["attribute"] = "attribute"
    attribute: str
    value: str

    def run(self, dataset: Dataset) -> Dataset:
        new_urls = []
        for zarr_url in dataset.zarr_urls:
            if str(zarr_url.attributes.get(self.attribute)) != self.value:
                zarr_url = zarr_url.model_copy(update={"hidden": True})
            new_urls.append(zarr_url)
        return dataset.model_copy(update={"zarr_urls": new_urls})


class TypeFilter(BaseFilter):
    type: Literal["type"] = "type"
    key: str
    value: bool

    def run(self, dataset: Dataset) -> Dataset:
        new_urls = []
        for zarr_url in dataset.zarr_urls:
            # Types are booleans, so compare directly (no string coercion).
            if zarr_url.types.get(self.key) != self.value:
                zarr_url = zarr_url.model_copy(update={"hidden": True})
            new_urls.append(zarr_url)
        return dataset.model_copy(update={"zarr_urls": new_urls})


# Discriminated union of concrete filters, so workflow steps round-trip to/from
# JSON without collapsing to the abstract ``BaseFilter``.
Filter = Annotated[AttributeFilter | TypeFilter, Field(discriminator="type")]
