"""Review questions preserve the literal server field-selector grammar."""

import pytest

from kuberich.domain.authorization import (
    AuthorizationScope,
    AuthorizationScopeKind,
    ResourceAccess,
    canonical_resource_access,
)
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.errors import AppError


@pytest.mark.parametrize("verb", ["list", "watch", "get"])
@pytest.mark.parametrize(
    "literal",
    [
        " metadata.name=demo",
        "metadata.name =demo",
        "metadata.name= demo",
        "metadata.name=demo ",
        "metadata.name=demo, status.phase=Running",
        "metadata.name\t=demo",
        "metadata.name=\tdemo",
        "metadata.name=demo,\nstatus.phase=Running",
    ],
)
def test_whitespace_normalization_cannot_create_an_authorization_name(verb, literal):
    query = ResourceQuery(field_selector=literal)
    question = ResourceAccess(
        verb,
        "",
        "v1",
        "pods",
        None,
        None,
        AuthorizationScope(AuthorizationScopeKind.NAMESPACE, "demo-apps"),
        query,
    )
    assert query.parameters["fieldSelector"] == literal
    with pytest.raises(AppError, match="literal"):
        canonical_resource_access(question)


def test_valid_literal_fields_and_label_whitespace_are_preserved():
    query = ResourceQuery(
        field_selector="metadata.name==demo,status.phase!=Pending",
        label_selector="app in (api, worker)",
    )
    question = ResourceAccess(
        "list",
        "",
        "v1",
        "pods",
        None,
        None,
        AuthorizationScope(AuthorizationScopeKind.NAMESPACE, "demo-apps"),
        query,
    )
    result = canonical_resource_access(question)
    assert result.name == "demo"
    assert result.query is query
    assert result.query.parameters == {
        "fieldSelector": "metadata.name==demo,status.phase!=Pending",
        "labelSelector": "app in (api, worker)",
    }
    assert canonical_resource_access(result) == result
