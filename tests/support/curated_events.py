"""Owned Event APIs with repeated occurrences and distinct object identities."""

from tests.support.curated_resources import CuratedResourcesApi
from tests.support.events import LAST, event_manifest, event_resource


class CuratedEventsApi(CuratedResourcesApi):
    def __init__(self, *, modern_only=False, **kwargs):
        super().__init__(**kwargs)
        for modern in (True,) if modern_only else (False, True):
            resource = event_resource(modern=modern)
            for index in range(7):
                body = event_manifest(
                    modern=modern,
                    uid=f"owned-{'modern' if modern else 'core'}-event-{index}",
                    object_uid="owned-start" if index != 4 else "replaced-pod",
                )
                body["metadata"].update(name=f"owned-event-{index}", resourceVersion="object-1")
                reference = body["regarding" if modern else "involvedObject"]
                reference["name"] = "owned-start"
                if index == 5:
                    reference.pop("uid")
                if index == 6:
                    body["reason"] = "FailedMount"
                if index == 3:
                    body.update(type="Normal", reason="Scheduled")
                if modern:
                    body["series"] = {
                        "count": [3, 5, False, 1, 2, 1, 1][index],
                        "lastObservedTime": LAST,
                    }
                else:
                    body["count"] = [3, 5, False, 1, 2, 1, 1][index]
                self.put(resource, body)
