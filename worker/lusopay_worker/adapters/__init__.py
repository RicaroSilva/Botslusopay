from .base import Adapter, AdapterRejected, LaunchSpec, Outcome, RunContext  # noqa: F401
from .flow import FlowAdapter
from .openbots import OpenBotsStudioAdapter
from .simulated import SimulatedAdapter
from .taskt import TasktCliAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    TasktCliAdapter.name: TasktCliAdapter,
    OpenBotsStudioAdapter.name: OpenBotsStudioAdapter,
    SimulatedAdapter.name: SimulatedAdapter,
    FlowAdapter.name: FlowAdapter,
}
