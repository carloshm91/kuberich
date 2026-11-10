# Run an HTTP benchmark

Send a short, explicitly confirmed HTTP load through a Service or a forward
started by KubeRich. You need write mode, an installed kubectl, permission to
read the Service and backend Pods, and `pods/portforward` permission. Test only
an endpoint you are authorized to load; GET can also have side effects.

## Configure the optional program

Install the matching Linux or macOS executable from the
[official Vegeta v12.13.0 release](https://github.com/tsenart/vegeta/releases/tag/v12.13.0).
Check its release checksum before using it. Configure its absolute path:

```yaml
schema_version: 1
benchmarks:
  schema_version: 1
  defaults:
    executable: /absolute/path/to/vegeta
    load:
      rate: 1
      concurrency: 1
      duration_seconds: 5
      timeout_seconds: 2
  contexts:
    demo-lab:
      load:
        duration_seconds: 3
```

Run `kuberich config check` after editing. Exact context entries override only
their supplied fields; other fields inherit global defaults. `executable: null`
disables the program for that entry. Settings never start a run. KubeRich does
not download, bundle, find or upgrade Vegeta, and normal startup and saved-result
browsing work without it. Vegeta uses the MIT license.

## Choose one backend and review the request

1. Select a Service in `:svc` and type `:benchmark`. Alternatively, open `:pf`,
   select a ready forward and choose **Benchmark** or press Shift+B.
2. Choose one current Ready/Running backend Pod and TCP port. A Service with
   several eligible backends requires your choice. The test measures that Pod,
   rather than distributing traffic across the whole Service.
3. Enter the method and relative target, for example `/health?mode=check`.
   Optional headers use one `Name: value` per line; the optional body is UTF-8.
   Keep the conservative load defaults unless your endpoint needs another limit.
4. Choose **Review F6**. Check the context, Service/Pod identities and ports,
   method, route, load, body size, authentication presence and local retention.
   Query values, header values and body contents are omitted from this review.
5. Choose **Run F7** deliberately. Cancel has initial focus. Changing any option
   requires a new review, and each approval starts at most one run.

HTTP/1.1 through a fresh loopback forward is supported. HTTPS/TLS-only endpoints,
arbitrary external URLs, selectorless Services, ExternalName Services, ambiguous
ports and incomplete backend lists are refused. An existing forward supplies a
selection only: the test creates a separate forward with no reconnection attempts.

Methods GET, HEAD, OPTIONS, POST, PUT, PATCH and DELETE all require the same
confirmation. Header values and body text remain visible while you edit them;
avoid sharing terminal recordings or screenshots that include those inputs.
Kubernetes API credentials are never copied into HTTP headers. You supply any
endpoint-specific authentication yourself.

## Keep the load small and stop it

The supported limits are 1–50 requested starts per second, 1–8 concurrent
requests, 1–30 seconds of configured duration and 1–5 seconds per request.
The nominal request budget is rate × duration; the tool can admit a boundary
attempt. Worker saturation can reduce the requested pacing, and later attempts
can catch up. The rate setting is not an exact ceiling for each wall-clock second.

Targets allow at most 2 KiB, headers at most 16 entries and 8 KiB combined, and
bodies at most 16 KiB. Routing/framing overrides, duplicate headers and control
characters are refused. Redirects, persistent connections and HTTP/2 are disabled.
Vegeta receives no inherited proxy, cloud or Kubernetes credential environment.

Choose **Cancel** or press Escape to stop and wait for cleanup. Leaving the form,
changing connection, tightening read-only mode or quitting also stops the test.
There is one active test per application, with no background or detach option.
Observed target replacement or forward loss makes the run incomplete; it never
switches to another Pod, restarts load or deliberately adopts another listener at the old port.

kubectl selects its remote Pod by name. Identity checks and loss notifications
reduce, but cannot eliminate, the race before a remote connection or a local
listener replacement. A request already scheduled or in flight can reach a
replacement listener while observed-loss cancellation is still draining. The
application waits for owned load to drain before returning or releasing its
client; it never claims that cancellation can unsend requests. Use the result's
completion state.

## Read the result

A complete result shows attempts, status counts, transport failures, HTTP
failures, redirects, latency and the exact load parameters. Latency percentiles
are estimates over all recorded attempts, including failures, and display in
milliseconds. Internal report durations use nanoseconds.

**Measured start rate** divides attempts by the time between the first and last
recorded starts. **Successful throughput** divides 2xx/3xx responses by that
interval plus the final response wait. These differ from configured pacing and
whole-run wall time. A single request has no measured interval, so rates show
N/A. Redirects count as tool successes but remain separate because they are not
followed. Status 0 identifies transport/body-read failures; 4xx/5xx are HTTP
failures. Raw tool error messages are discarded, and distinct messages are never
presented as an error count.

The tool retains no response bodies but still drains them. Its zero retained
byte count is not a network-throughput measurement or a cap on received bytes,
headers or process memory. Requests/second is the displayed throughput measure.
Cancellation, target loss, invalid output, tool failures and incomplete cleanup
never become a successful zero-error result. A save failure leaves the result
visible in the form and reports that it was not confirmed saved.

## Browse saved results locally

Open `:benchmarks`, or start with `kuberich --command benchmarks`. The browser
does not connect, execute tools, create directories or prune records. Select a
row and choose **Open**; **Refresh** rereads the local files. **Delete** requires
confirmation of the selected filename and deletes only that saved record.

Records live under the platform user-state directory's `kuberich/benchmarks`
folder. Use `--benchmark-directory /absolute/path` to select a separate local
results folder without creating it during launch or browsing. Each private JSON record is at most 32 KiB; storage allows 100 records,
4 MiB combined and 30 days. Saving explicitly may remove expired records or the
oldest records to make room. Opening the browser never performs that cleanup.

Saved fields include safe Service/Pod names and UIDs, context/namespace, remote
ports, method, load settings, times, completion and validated metrics. Request
paths, queries, header values, body, raw reports and credentials are omitted.
Names can still identify your workload; inspect a record before sharing it.
Metadata cannot connect to a cluster or authorize replay.

Symlinks, hard links, malformed or foreign files, changed identities and directory
overflow cause a visible storage refusal. KubeRich does not delete unknown files
to repair the folder. Correct the local cause, then Refresh. See
[local exports](exports.md) for the separate general-purpose artifact workflow.
