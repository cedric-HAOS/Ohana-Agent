# configuration/infrastructure_validator.py

from ipaddress import ip_address

from configuration.infrastructure import InfrastructureConfig


class InfrastructureValidationError(ValueError):
    """Raised when an infrastructure configuration is invalid."""


class InfrastructureValidator:
    """Validates an infrastructure configuration."""

    def validate(self, config: InfrastructureConfig) -> None:
        """Validate an infrastructure configuration."""
        self._validate_node_ids_are_unique(config)
        self._validate_service_ids_are_unique(config)
        self._validate_node_addresses(config)
        self._validate_service_nodes_exist(config)
        self._validate_service_ports(config)
        self._validate_topology_device_ids_are_unique(config)
        self._validate_topology_device_addresses(config)
        self._validate_topology_device_nodes_exist(config)
        self._validate_topology_node_references_are_unique(config)
        self._validate_topology_link_ids_are_unique(config)
        self._validate_topology_link_devices_exist(config)
        self._validate_topology_layout_ids_are_unique(config)
        self._validate_topology_layout_positions(config)

    def _validate_node_ids_are_unique(
        self,
        config: InfrastructureConfig,
    ) -> None:
        node_ids = [node.id for node in config.nodes]

        if len(node_ids) != len(set(node_ids)):
            raise InfrastructureValidationError("Node identifiers must be unique.")

    def _validate_service_ids_are_unique(
        self,
        config: InfrastructureConfig,
    ) -> None:
        service_ids = [service.id for service in config.services]

        if len(service_ids) != len(set(service_ids)):
            raise InfrastructureValidationError("Service identifiers must be unique.")

    def _validate_node_addresses(
        self,
        config: InfrastructureConfig,
    ) -> None:
        for node in config.nodes:
            if node.endpoint.type != "ip":
                raise InfrastructureValidationError(
                    f"Unsupported endpoint type: {node.endpoint.type}"
                )

            try:
                ip_address(node.endpoint.address)
            except ValueError as exc:
                raise InfrastructureValidationError(
                    f"Invalid IP address: {node.endpoint.address}"
                ) from exc

    def _validate_service_nodes_exist(
        self,
        config: InfrastructureConfig,
    ) -> None:
        node_ids = {node.id for node in config.nodes}

        for service in config.services:
            if service.node not in node_ids:
                raise InfrastructureValidationError(
                    f"Service '{service.id}' references unknown node '{service.node}'."
                )

    def _validate_service_ports(
        self,
        config: InfrastructureConfig,
    ) -> None:
        for service in config.services:
            if service.port is None:
                continue

            if service.port < 1 or service.port > 65535:
                raise InfrastructureValidationError(
                    f"Invalid port '{service.port}' for service '{service.id}'."
                )

    def _validate_topology_device_ids_are_unique(
        self,
        config: InfrastructureConfig,
    ) -> None:
        if config.topology is None:
            return

        device_ids = [device.id for device in config.topology.devices]

        if len(device_ids) != len(set(device_ids)):
            raise InfrastructureValidationError(
                "Topology device identifiers must be unique."
            )

    def _validate_topology_device_addresses(
        self,
        config: InfrastructureConfig,
    ) -> None:
        if config.topology is None:
            return

        for device in config.topology.devices:
            if device.address is None:
                continue

            try:
                ip_address(device.address)
            except ValueError as exc:
                raise InfrastructureValidationError(
                    f"Invalid IP address for topology device "
                    f"'{device.id}': {device.address}"
                ) from exc

    def _validate_topology_device_nodes_exist(
        self,
        config: InfrastructureConfig,
    ) -> None:
        if config.topology is None:
            return

        node_ids = {node.id for node in config.nodes}

        for device in config.topology.devices:
            if device.node is None:
                continue

            if device.node not in node_ids:
                raise InfrastructureValidationError(
                    f"Topology device '{device.id}' references "
                    f"unknown node '{device.node}'."
                )

    def _validate_topology_node_references_are_unique(
        self,
        config: InfrastructureConfig,
    ) -> None:
        if config.topology is None:
            return

        node_ids = [
            device.node for device in config.topology.devices if device.node is not None
        ]

        if len(node_ids) != len(set(node_ids)):
            raise InfrastructureValidationError(
                "Topology node references must be unique."
            )

    def _validate_topology_link_ids_are_unique(
        self,
        config: InfrastructureConfig,
    ) -> None:
        if config.topology is None:
            return

        link_ids = [link.id for link in config.topology.links]

        if len(link_ids) != len(set(link_ids)):
            raise InfrastructureValidationError(
                "Topology link identifiers must be unique."
            )

    def _validate_topology_link_devices_exist(
        self,
        config: InfrastructureConfig,
    ) -> None:
        if config.topology is None:
            return

        device_ids = {device.id for device in config.topology.devices}

        for link in config.topology.links:
            if link.source == link.target:
                raise InfrastructureValidationError(
                    f"Topology link '{link.id}' must connect two different devices."
                )

            unknown_device_ids = [
                device_id
                for device_id in (
                    link.source,
                    link.target,
                )
                if device_id not in device_ids
            ]

            if unknown_device_ids:
                unknown = ", ".join(unknown_device_ids)
                raise InfrastructureValidationError(
                    f"Topology link '{link.id}' references unknown devices: {unknown}."
                )

    def _validate_topology_layout_ids_are_unique(
        self,
        config: InfrastructureConfig,
    ) -> None:
        if config.topology is None:
            return

        layout_ids = [layout.id for layout in config.topology.layouts]

        if len(layout_ids) != len(set(layout_ids)):
            raise InfrastructureValidationError(
                "Topology layout identifiers must be unique."
            )

    def _validate_topology_layout_positions(
        self,
        config: InfrastructureConfig,
    ) -> None:
        if config.topology is None:
            return

        device_ids = {device.id for device in config.topology.devices}

        for layout in config.topology.layouts:
            unknown_device_ids = sorted(set(layout.positions) - device_ids)

            if unknown_device_ids:
                unknown = ", ".join(unknown_device_ids)
                raise InfrastructureValidationError(
                    f"Topology layout '{layout.id}' references "
                    f"unknown devices: {unknown}."
                )

            grid_cells = [
                (position.column, position.row)
                for position in layout.positions.values()
            ]

            if len(grid_cells) != len(set(grid_cells)):
                raise InfrastructureValidationError(
                    f"Topology layout '{layout.id}' contains duplicate grid positions."
                )
