"""Parse literal authorization questions, then resolve them against owned discovery."""

import shlex
from dataclasses import dataclass

from kuberich.domain.authorization import (
    AuthorizationIntent,
    AuthorizationMode,
    AuthorizationScope,
    AuthorizationScopeKind,
    NonResourceAccess,
    RbacSubject,
    RbacSubjectKind,
    ResourceAccess,
)
from kuberich.domain.connections import namespace_name
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import Discovery, api_segment, resource_name
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

AUTHORIZATION_COMMANDS = frozenset({"rbac", "rules", "can-i", "who-can"})


@dataclass(frozen=True)
class AuthorizationCommand:
    mode: AuthorizationMode
    scope: AuthorizationScope | None
    subject: RbacSubject | None
    verb: str | None
    resource_name: str | None
    group: str | None
    name: str | None
    subresource: str | None
    non_resource_url: str | None


def authorization_command(text: str) -> AuthorizationCommand:
    """Parse one complete command without discovery, helpers, or network access."""
    validate_argument(text)
    try:
        words = shlex.split(text)
    except ValueError:
        raise AppError("Authorization commands contain an unfinished quoted value.") from None
    if not words or words[0].lower() not in AUTHORIZATION_COMMANDS:
        raise AppError("Use :rbac, :rules NAMESPACE, :can-i or :who-can.")
    verb, words = words[0].lower(), words[1:]
    positional: list[str] = []
    scope = None
    subresource = non_resource_url = None
    index = 0
    while index < len(words):
        word = words[index]
        if word in {"--namespace", "--all-namespaces", "--cluster"}:
            if scope is not None:
                raise AppError("Choose exactly one authorization scope.")
            namespace = None
            kind = AuthorizationScopeKind.CLUSTER
            if word == "--namespace":
                index += 1
                if index == len(words):
                    raise AppError("--namespace requires a namespace.")
                namespace = namespace_name(words[index])
                kind = AuthorizationScopeKind.NAMESPACE
            elif word == "--all-namespaces":
                kind = AuthorizationScopeKind.ALL_NAMESPACES
            scope = AuthorizationScope(kind, namespace)
        elif word in {"--subresource", "--non-resource-url"}:
            index += 1
            if index == len(words):
                raise AppError(f"{word} requires one literal value.")
            if word == "--subresource":
                if subresource is not None:
                    raise AppError("Choose one subresource.")
                subresource = api_segment(words[index])
            else:
                if non_resource_url is not None:
                    raise AppError("Choose one non-resource URL.")
                non_resource_url = words[index]
        elif word.startswith("-"):
            raise AppError("Unknown authorization option.")
        else:
            positional.append(word)
        index += 1
    subject = None
    request_verb = resource = group = name = None
    if verb == "rbac":
        if subresource is not None or non_resource_url is not None:
            raise AppError("RBAC browsing accepts only a mode, subject and scope.")
        if not positional or positional == ["subjects"]:
            mode = AuthorizationMode.SUBJECTS
        elif positional in (["bindings"], ["roles"]):
            mode = AuthorizationMode(positional[0])
        elif len(positional) >= 3 and positional[0] == "subject":
            kind_name = positional[1]
            if kind_name in {"user", "group"} and len(positional) == 3:
                subject = RbacSubject(
                    RbacSubjectKind.USER if kind_name == "user" else RbacSubjectKind.GROUP,
                    positional[2],
                    None,
                )
            elif kind_name == "serviceaccount" and len(positional) == 4:
                subject = RbacSubject(RbacSubjectKind.SERVICE_ACCOUNT, positional[3], positional[2])
            else:
                raise AppError(
                    "Use :rbac subject user/group NAME or serviceaccount NAMESPACE NAME."
                )
            mode = AuthorizationMode.SUBJECT
        else:
            raise AppError("Use :rbac subjects/bindings/roles or :rbac subject KIND NAME.")
    elif verb == "rules":
        if (
            len(positional) != 1
            or scope is not None
            or subresource is not None
            or non_resource_url is not None
        ):
            raise AppError("Use :rules NAMESPACE.")
        scope = AuthorizationScope(AuthorizationScopeKind.NAMESPACE, positional[0])
        mode = AuthorizationMode.SELF_RULES
    else:
        mode = AuthorizationMode.REVIEW if verb == "can-i" else AuthorizationMode.WHO_CAN
        if not positional:
            raise AppError("An access question requires a verb and resource or non-resource URL.")
        request_verb = positional[0]
        if non_resource_url is not None:
            if len(positional) != 1 or scope is not None or subresource is not None:
                raise AppError("Non-resource questions accept VERB --non-resource-url PATH only.")
            NonResourceAccess(request_verb, non_resource_url)
            scope = AuthorizationScope(AuthorizationScopeKind.CLUSTER, None)
        else:
            if not 2 <= len(positional) <= 3:
                raise AppError("Use VERB RESOURCE[.GROUP] [NAME] [--subresource NAME] [SCOPE].")
            resource, dot, group_value = positional[1].partition(".")
            api_segment(resource)
            if dot:
                group = "" if group_value == "core" else api_segment(group_value)
            if len(positional) == 3:
                name = resource_name(positional[2])
            # Validate the verb before discovery is available.
            NonResourceAccess(request_verb, "/")
    return AuthorizationCommand(
        mode, scope, subject, request_verb, resource, group, name, subresource, non_resource_url
    )


def authorization_intent(
    command: AuthorizationCommand, discovery: Discovery, namespace: str | None
) -> AuthorizationIntent:
    """Resolve the served descriptor once; local filter text is never an access selector."""
    scope = command.scope or AuthorizationScope(
        AuthorizationScopeKind.NAMESPACE
        if namespace is not None
        else AuthorizationScopeKind.ALL_NAMESPACES,
        namespace,
    )
    access: ResourceAccess | NonResourceAccess | None = None
    if command.mode in {AuthorizationMode.REVIEW, AuthorizationMode.WHO_CAN}:
        if command.verb is None:
            raise AppError("An access question requires a verb.")
        if command.non_resource_url is not None:
            scope = AuthorizationScope(AuthorizationScopeKind.CLUSTER, None)
            access = NonResourceAccess(command.verb, command.non_resource_url)
        else:
            if command.resource_name is None:
                raise AppError("An access question requires a resource.")
            resource = discovery.resolve(command.resource_name, group=command.group)
            if resource.namespaced:
                if scope.kind is AuthorizationScopeKind.CLUSTER:
                    raise AppError(
                        "A namespaced resource requires a namespace or all-namespace scope."
                    )
            else:
                if (
                    command.scope is not None
                    and command.scope.kind is not AuthorizationScopeKind.CLUSTER
                ):
                    raise AppError("A cluster resource requires --cluster, with no namespace.")
                scope = AuthorizationScope(AuthorizationScopeKind.CLUSTER, None)
            access = ResourceAccess(
                command.verb,
                resource.group,
                resource.version,
                resource.name,
                command.subresource,
                command.name,
                scope,
                ResourceQuery(),
            )
    return AuthorizationIntent(command.mode, scope, subject=command.subject, access=access)
