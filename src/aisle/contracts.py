"""Versioned public task contract and private execution configuration."""

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Budget(BaseModel):
    max_rounds: int = Field(gt=0)
    max_samples: int = Field(gt=0)


class Metric(BaseModel):
    name: Literal["best_delta_e", "safety_lexicographic"]
    direction: Literal["minimize"]
    success_threshold: float = Field(gt=0)


class Simulation(BaseModel):
    model_config = ConfigDict(extra="allow")
    adapter: Literal["lightgbm"]
    asset_env: str = "AISLE_SIM_MODEL"
    version: str = Field(min_length=1)
    validation_status: Literal["pending", "accepted"]


class RealLab(BaseModel):
    model_config = ConfigDict(extra="allow")
    adapter: Literal["manual"]
    sop_path: str = Field(min_length=1)
    lab_id: str = Field(min_length=1)
    readiness: Literal["pending", "accepted"]


class TaskManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["1.0"]
    task_id: str = Field(pattern=r"^[a-z][a-z0-9_\-]+$")
    version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kind: Literal["optimization", "safety"]
    description: str = Field(min_length=1)
    target: dict[str, Any]
    action_schema: dict[str, Any]
    observation_schema: dict[str, Any]
    budget: Budget
    metric: Metric
    sim: Simulation
    real: RealLab
    provenance: dict[str, Any]
    review: dict[str, Any]

    @model_validator(mode="after")
    def check_schemas(self):
        Draft202012Validator.check_schema(self.action_schema)
        Draft202012Validator.check_schema(self.observation_schema)
        if self.target.get("success_threshold") != self.metric.success_threshold:
            raise ValueError("target.success_threshold must match metric.success_threshold")
        expected_metric = "safety_lexicographic" if self.kind == "safety" else "best_delta_e"
        if self.metric.name != expected_metric:
            raise ValueError("metric.name does not match the task kind")
        if self.review.get("status") not in {
            "draft",
            "engineering_verified",
            "scientifically_accepted",
        }:
            raise ValueError("review.status must identify the acceptance stage")
        return self

    def public(self) -> dict:
        return self.model_dump(
            include={
                "schema_version",
                "task_id",
                "version",
                "title",
                "kind",
                "description",
                "target",
                "action_schema",
                "observation_schema",
                "budget",
                "metric",
            }
        )

    @classmethod
    def load(cls, path: str | Path):
        path = Path(path).resolve()
        value = cls.model_validate(yaml.safe_load(path.read_text()))
        sop = (path.parent / value.real.sop_path).resolve()
        if not sop.is_relative_to(path.parent) or not sop.is_file():
            raise ValueError("real.sop_path must name a file inside the task package")
        return value


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(pattern=r"^[a-zA-Z0-9_\-\.]+$")
    model: str
    harness: Literal["json", "tools", "scripted"]
    harness_version: str = "1.0"
    base_url_env: str = "AISLE_MODEL_BASE_URL"
    api_key_env: str = "AISLE_MODEL_API_KEY"
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int = Field(default=2048, gt=0)
    token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    extra_body: dict[str, Any] = Field(default_factory=dict)
    max_turns: int = Field(default=30, gt=0)
    skills: list[str] = Field(default_factory=list)
    scripted_actions: list[dict] = Field(default_factory=list)

    @classmethod
    def load(cls, path):
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))
