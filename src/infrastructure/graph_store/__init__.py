"""
Graph Store Interface
=====================

Provides an abstraction for graph database operations.
Used for representing relationships between claims, evidence, and entities.

EXTENSION_POINT: A2+ will implement concrete graph store (Neo4j, etc.)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class NodeType(str, Enum):
    """Types of nodes in the truth graph."""

    CLAIM = "Claim"
    EVIDENCE = "Evidence"
    ENTITY = "Entity"
    DOCUMENT = "Document"
    ORGANIZATION = "Organization"
    PERSON = "Person"
    FINANCIAL_STATEMENT = "FinancialStatement"


class EdgeType(str, Enum):
    """Types of edges in the truth graph."""

    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    REFERENCES = "REFERENCES"
    DERIVED_FROM = "DERIVED_FROM"
    CONTAINS = "CONTAINS"
    RELATED_TO = "RELATED_TO"
    AUTHORED_BY = "AUTHORED_BY"
    BELONGS_TO = "BELONGS_TO"


@dataclass
class Node:
    """A node in the truth graph."""

    id: str
    type: NodeType
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None


@dataclass
class Edge:
    """An edge connecting two nodes in the truth graph."""

    id: str
    type: EdgeType
    source_id: str
    target_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    created_at: Optional[datetime] = None


@dataclass
class GraphQuery:
    """A query against the graph store."""

    # EXTENSION_POINT: A2+ will add query DSL
    pattern: str
    parameters: dict[str, Any] = field(default_factory=dict)
    limit: int = 100


@dataclass
class GraphQueryResult:
    """Result of a graph query."""

    nodes: list[Node]
    edges: list[Edge]
    paths: list[list[str]] = field(default_factory=list)


class GraphStoreInterface(ABC):
    """
    Abstract interface for graph database operations.

    EXTENSION_POINT: A2+ will implement concrete graph store.
    """

    @abstractmethod
    async def create_node(self, node: Node) -> Node:
        """Create a node in the graph."""
        pass

    @abstractmethod
    async def get_node(self, node_id: str) -> Optional[Node]:
        """Get a node by ID."""
        pass

    @abstractmethod
    async def update_node(self, node_id: str, properties: dict[str, Any]) -> Optional[Node]:
        """Update node properties."""
        pass

    @abstractmethod
    async def delete_node(self, node_id: str) -> bool:
        """Delete a node and its edges."""
        pass

    @abstractmethod
    async def create_edge(self, edge: Edge) -> Edge:
        """Create an edge between nodes."""
        pass

    @abstractmethod
    async def get_edges(
        self,
        node_id: str,
        edge_type: Optional[EdgeType] = None,
        direction: str = "both",
    ) -> list[Edge]:
        """Get edges connected to a node."""
        pass

    @abstractmethod
    async def delete_edge(self, edge_id: str) -> bool:
        """Delete an edge."""
        pass

    @abstractmethod
    async def query(self, query: GraphQuery) -> GraphQueryResult:
        """Execute a graph query."""
        pass

    @abstractmethod
    async def find_path(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 5,
    ) -> list[list[str]]:
        """Find paths between two nodes."""
        pass

    @abstractmethod
    async def get_neighbors(
        self,
        node_id: str,
        depth: int = 1,
        node_types: Optional[list[NodeType]] = None,
    ) -> list[Node]:
        """Get neighboring nodes."""
        pass


class NullGraphStore(GraphStoreInterface):
    """
    Null implementation of graph store.

    EXTENSION_POINT: This is replaced with real graph store in A2+.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}

    async def create_node(self, node: Node) -> Node:
        self._nodes[node.id] = node
        return node

    async def get_node(self, node_id: str) -> Optional[Node]:
        return self._nodes.get(node_id)

    async def update_node(self, node_id: str, properties: dict[str, Any]) -> Optional[Node]:
        if node_id in self._nodes:
            self._nodes[node_id].properties.update(properties)
            return self._nodes[node_id]
        return None

    async def delete_node(self, node_id: str) -> bool:
        if node_id in self._nodes:
            del self._nodes[node_id]
            # Remove connected edges
            self._edges = {
                k: v for k, v in self._edges.items()
                if v.source_id != node_id and v.target_id != node_id
            }
            return True
        return False

    async def create_edge(self, edge: Edge) -> Edge:
        self._edges[edge.id] = edge
        return edge

    async def get_edges(
        self,
        node_id: str,
        edge_type: Optional[EdgeType] = None,
        direction: str = "both",
    ) -> list[Edge]:
        result = []
        for edge in self._edges.values():
            matches = False
            if direction in ("both", "outgoing") and edge.source_id == node_id:
                matches = True
            if direction in ("both", "incoming") and edge.target_id == node_id:
                matches = True
            if matches and (edge_type is None or edge.type == edge_type):
                result.append(edge)
        return result

    async def delete_edge(self, edge_id: str) -> bool:
        if edge_id in self._edges:
            del self._edges[edge_id]
            return True
        return False

    async def query(self, query: GraphQuery) -> GraphQueryResult:
        # EXTENSION_POINT: Real query execution in A2+
        return GraphQueryResult(nodes=[], edges=[])

    async def find_path(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 5,
    ) -> list[list[str]]:
        # EXTENSION_POINT: Real path finding in A2+
        return []

    async def get_neighbors(
        self,
        node_id: str,
        depth: int = 1,
        node_types: Optional[list[NodeType]] = None,
    ) -> list[Node]:
        # EXTENSION_POINT: Real neighbor traversal in A2+
        result = []
        edges = await self.get_edges(node_id)
        for edge in edges:
            neighbor_id = edge.target_id if edge.source_id == node_id else edge.source_id
            if neighbor_id in self._nodes:
                node = self._nodes[neighbor_id]
                if node_types is None or node.type in node_types:
                    result.append(node)
        return result
