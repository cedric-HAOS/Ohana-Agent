"""Tests for the supported public imports of Ohana-Agent."""

from ohana_agent.configuration.builders import (
    DNSConfigurationBuilder,
    InfrastructureBuilder,
)
from ohana_agent.configuration.loaders import DNSConfigLoader, InfrastructureLoader
from ohana_agent.core import Executor, Registry, Runtime, Statistics
from ohana_agent.infrastructure import (
    Endpoint,
    EndpointRuntime,
    EndpointType,
    HealthStatus,
    Infrastructure,
    InfrastructureCapability,
    InfrastructureCapabilityCalculator,
    InfrastructureHealthUpdate,
    InfrastructureRuntime,
    Node,
    NodeRuntime,
    ObservationManager,
    SchedulerObservationHandler,
    Service,
    ServiceRuntime,
    ServiceType,
)
from ohana_agent.observation import (
    EventPublisher,
    InfrastructureObservationMapper,
    Observation,
    ObservationDefinition,
    ObservationEngine,
    ObservationEventPublisher,
    ObservationExporter,
    ObservationExportHandler,
    ObservationExportPipeline,
    ObservationFactory,
    ObservationPublished,
    ObservationRuntime,
    ObservationSerializer,
    ObservationState,
    ObservationStatus,
    ObservationStatusMapper,
    Observer,
    ObserverResult,
    ObserverResultMapper,
    ObserverRuntime,
    ObserverState,
    ObserverStatistics,
    PluginObservationDispatcher,
    PluginObservationExecutor,
)
from ohana_agent.observation.checks import BaseCheck, DNSCheck, FakeCheck
from ohana_agent.observation.exporters import (
    HttpVisionClient,
    InMemoryObservationExporter,
    VisionClient,
    VisionClientError,
    VisionObservationExporter,
    VisionObservationMapper,
)
from ohana_agent.persistence import (
    MemoryEntry,
    MemoryManager,
    MemoryScope,
    MemorySerializer,
    MemoryStatistics,
    MemoryStorage,
    PersistentMemory,
    RuntimeMemory,
    SessionMemory,
)
from ohana_agent.plugins.dns import (
    ConfiguredDNSCheck,
    DNSCapabilityRuntime,
    DNSCheckFailed,
    DNSCheckResult,
    DNSCheckStarted,
    DNSCheckSucceeded,
    DNSConfig,
    DNSPlugin,
    DNSPolicyConfig,
    DNSResolver,
    DNSResult,
    DNSRuntime,
    DNSServer,
    DNSServerConfig,
    DNSServerRuntime,
    DNSStatistics,
)
from ohana_agent.plugins.runtime import (
    Plugin,
    PluginAlreadyLoadedError,
    PluginCommand,
    PluginDescriptor,
    PluginDiscovery,
    PluginError,
    PluginLoader,
    PluginLoadError,
    PluginLoadFailed,
    PluginManager,
    PluginManifest,
    PluginNotFoundError,
    PluginRegistered,
    PluginUnregistered,
)
from ohana_agent.plugins.runtime.discovery import (
    DiscoveryProvider,
    LocalDirectoryProvider,
)
from ohana_agent.plugins.runtime.factory import PluginFactory, PythonPluginFactory
from ohana_agent.scheduler import (
    BaseTrigger,
    Clock,
    CronTrigger,
    DispatcherTaskExecutor,
    DryRunTaskExecutor,
    FailingTaskExecutor,
    FakeClock,
    IntervalTrigger,
    OneShotTrigger,
    ScheduledTaskExecuted,
    ScheduledTaskFailed,
    ScheduledTaskTriggered,
    Scheduler,
    SchedulerEvent,
    SchedulerRuntime,
    SchedulerStarted,
    SchedulerState,
    SchedulerStatistics,
    SchedulerStopped,
    SchedulerTicked,
    SystemClock,
    Task,
    TaskExecutor,
    TaskRegistry,
    TaskState,
    Trigger,
)


def test_core_public_contracts_are_importable() -> None:
    assert Executor is not None
    assert Registry is not None
    assert Runtime is not None
    assert Statistics is not None


def test_infrastructure_public_contracts_are_importable() -> None:
    public_contracts = (
        Endpoint,
        EndpointRuntime,
        EndpointType,
        HealthStatus,
        Infrastructure,
        InfrastructureCapability,
        InfrastructureCapabilityCalculator,
        InfrastructureHealthUpdate,
        InfrastructureRuntime,
        Node,
        NodeRuntime,
        ObservationManager,
        SchedulerObservationHandler,
        Service,
        ServiceRuntime,
        ServiceType,
    )

    assert all(contract is not None for contract in public_contracts)


def test_observer_public_contracts_are_importable() -> None:
    public_contracts = (
        EventPublisher,
        InfrastructureObservationMapper,
        Observation,
        ObservationDefinition,
        ObservationEngine,
        ObservationEventPublisher,
        ObservationExportHandler,
        ObservationExporter,
        ObservationExportPipeline,
        ObservationFactory,
        ObservationPublished,
        ObservationRuntime,
        ObservationSerializer,
        ObservationState,
        ObservationStatus,
        ObservationStatusMapper,
        Observer,
        ObserverResult,
        ObserverResultMapper,
        ObserverRuntime,
        ObserverState,
        ObserverStatistics,
        PluginObservationDispatcher,
        PluginObservationExecutor,
    )

    assert all(contract is not None for contract in public_contracts)


def test_observer_supporting_public_contracts_are_importable() -> None:
    public_contracts = (
        BaseCheck,
        DNSCheck,
        FakeCheck,
        HttpVisionClient,
        InMemoryObservationExporter,
        VisionClient,
        VisionClientError,
        VisionObservationExporter,
        VisionObservationMapper,
    )

    assert all(contract is not None for contract in public_contracts)


def test_plugin_public_contracts_are_importable() -> None:
    public_contracts = (
        Plugin,
        PluginAlreadyLoadedError,
        PluginCommand,
        PluginDescriptor,
        PluginDiscovery,
        PluginError,
        PluginLoadError,
        PluginLoadFailed,
        PluginLoader,
        PluginManager,
        PluginManifest,
        PluginNotFoundError,
        PluginRegistered,
        PluginUnregistered,
        DiscoveryProvider,
        LocalDirectoryProvider,
        PluginFactory,
        PythonPluginFactory,
    )

    assert all(contract is not None for contract in public_contracts)


def test_scheduler_public_contracts_are_importable() -> None:
    public_contracts = (
        BaseTrigger,
        Clock,
        CronTrigger,
        DispatcherTaskExecutor,
        DryRunTaskExecutor,
        FailingTaskExecutor,
        FakeClock,
        IntervalTrigger,
        OneShotTrigger,
        ScheduledTaskExecuted,
        ScheduledTaskFailed,
        ScheduledTaskTriggered,
        Scheduler,
        SchedulerEvent,
        SchedulerRuntime,
        SchedulerStarted,
        SchedulerState,
        SchedulerStatistics,
        SchedulerStopped,
        SchedulerTicked,
        SystemClock,
        Task,
        TaskExecutor,
        TaskRegistry,
        TaskState,
        Trigger,
    )

    assert all(contract is not None for contract in public_contracts)


def test_dns_plugin_public_contracts_are_importable() -> None:
    public_contracts = (
        ConfiguredDNSCheck,
        DNSCapabilityRuntime,
        DNSCheckFailed,
        DNSCheckResult,
        DNSCheckStarted,
        DNSCheckSucceeded,
        DNSConfig,
        DNSPlugin,
        DNSPolicyConfig,
        DNSResolver,
        DNSResult,
        DNSRuntime,
        DNSServer,
        DNSServerConfig,
        DNSServerRuntime,
        DNSStatistics,
    )

    assert all(contract is not None for contract in public_contracts)


def test_memory_public_contracts_are_importable() -> None:
    public_contracts = (
        MemoryEntry,
        MemoryManager,
        MemoryScope,
        MemorySerializer,
        MemoryStatistics,
        MemoryStorage,
        PersistentMemory,
        RuntimeMemory,
        SessionMemory,
    )

    assert all(contract is not None for contract in public_contracts)


def test_configuration_support_public_contracts_are_importable() -> None:
    public_contracts = (
        DNSConfigurationBuilder,
        InfrastructureBuilder,
        DNSConfigLoader,
        InfrastructureLoader,
    )

    assert all(contract is not None for contract in public_contracts)
