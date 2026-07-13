try:
    from pydantic import BaseModel, Field
except ModuleNotFoundError:
    class _FieldInfo:
        def __init__(self, default=None, default_factory=None):
            self.default = default
            self.default_factory = default_factory

    def Field(default=None, default_factory=None):
        return _FieldInfo(default=default, default_factory=default_factory)

    class BaseModel:
        def __init__(self, **kwargs):
            annotations = {}
            for cls in reversed(type(self).mro()):
                annotations.update(getattr(cls, "__annotations__", {}))

            for name in annotations:
                if name in kwargs:
                    value = kwargs[name]
                else:
                    default = getattr(type(self), name, None)
                    if isinstance(default, _FieldInfo):
                        value = default.default_factory() if default.default_factory else default.default
                    else:
                        value = default
                setattr(self, name, value)

        def model_dump(self):
            return dict(self.__dict__)


class ParseResponse(BaseModel):
    status: str = Field(default="ok")
    filename: str | None = None
    mime_type: str | None = None
    source_type: str
    characters: int
    text: str
    warnings: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    status: str = Field(default="error")
    error: str
    detail: str | None = None
