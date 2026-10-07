class ExpressionInfo:
    errors: list[str]

class Licensing:
    def validate(self, expression: str, strict: bool = ...) -> ExpressionInfo: ...

def get_spdx_licensing() -> Licensing: ...
