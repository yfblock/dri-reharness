# Generic Registration Root Design

## Goal

Make Linux registration verification expressible for both traditional driver
tables and framework objects registered directly from module initialization,
without adding bus- or driver-specific branches to the AST oracle.

## Scope

This increment covers the declarative registration contract and its AST proof
for a `net_device` root registered by `register_netdev`. It also defines the
generic extension points that the next profile can reuse:

- `driver_root` remains the kind for a traditional driver table with probe and
  remove callbacks.
- `object_root` represents a typed framework object passed to a registration
  API from module initialization. It does not imply a `.probe` callback.
- `identity_field: "none"` explicitly means that the manifest has no stable
  driver or registrar name to reconcile in the AST oracle.
- typed links continue to connect a registered root object to its callback
  table; for networking this is `net_device.netdev_ops` to
  `net_device_ops`.

The network runtime remains a representative `net_device` lifecycle fixture.
This increment does not claim RX/TX, DMA, IRQ, offload, hotplug, or complete
networking-subsystem coverage.

## Data Contract

The Linux registration catalog will contain these network entries:

```json
{
  "tables": [
    {"id": "net_device", "record": "net_device", "role": "root"},
    {"id": "net_device_ops", "record": "net_device_ops", "role": "callback"}
  ],
  "registration_apis": [
    {"name": "register_netdev", "kind": "object_root", "argument": 0,
     "type": "struct net_device *", "table": "net_device"}
  ],
  "links": [
    {"owner_table": "net_device", "field": "netdev_ops",
     "target_table": "net_device_ops"}
  ]
}
```

The network profile and materialized experiment manifest use the same
contract. No runner branch is added for `network`.

## AST Behavior

The oracle will accept `driver_root` and `object_root` through one root-call
path. Both must resolve to an external registration API, have the exact typed
object argument, and be reachable from a module-init target. Only
`driver_root` exposes root `.probe`/`.remove` membership; `object_root` can
still expose callback routes through catalogued typed links.

For a registered `net_device` object, the existing fixed-point link analysis
will prove the exact `net_device_ops` object and its static callback
initializers. The proof remains fail-closed for shadowed APIs, wrong argument
types, controlled registration calls, missing object identity, or callbacks
not reachable through the registered object.

When `identity_field` is `none`, runtime identity comparison is skipped and
reported as intentionally unrequested. All existing identity modes retain
their current behavior.

## Testing

Tests will first assert that the catalog rejects an unknown root kind and that
the network profile exposes its complete contract. An AST fixture will then
prove `register_netdev` plus `net_device.netdev_ops` callback ownership and
reject an unregistered callback object. Existing registration, profile,
manifest, and runtime tests must remain green.

The final verification includes the focused Python tests, the full Python
regression suite with the repository `PYTHONPATH`, a strict network module
compile, the network QEMU profile, and the complete post-parser-fix
8-profile matrix.

## Non-Goals

This design does not add a generic packet-path oracle, emulate every QEMU
network device, or turn optional upstream kselftests into required acceptance
checks. Those require separate profile-owned test contracts.
