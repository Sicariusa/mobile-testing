"""Mobile QA Test Runner — execution engine.

Layered: device -> observation -> (resolver/recovery/executor/validator)
-> evidence/report. Everything above the device layer reaches the device only
through the :class:`~engine.device.Device` interface, which is what lets the
whole engine be exercised against a FakeDevice with no Android present.
"""
