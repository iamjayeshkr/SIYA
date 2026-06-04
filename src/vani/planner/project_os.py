"""
src/vani/planner/project_os.py — Long-Running Project Tracker and Planner OS
"""

from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from vani.config import PROJECT_ROOT

logger = logging.getLogger("vani.planner.project_os")
PROJECTS_FILE = PROJECT_ROOT / "conversations" / "projects.json"


class Task:
    def __init__(self, task_id: str, name: str, status: str = "todo", blockers: List[str] = None) -> None:
        self.id = task_id
        self.name = name
        self.status = status  # todo, running, done, failed
        self.blockers = blockers or []  # List of Task IDs
        self.risk_level = "low"  # low, medium, high

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "blockers": self.blockers,
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Task:
        t = cls(data["id"], data["name"], data["status"], data["blockers"])
        t.risk_level = data.get("risk_level", "low")
        return t


class Milestone:
    def __init__(self, milestone_id: str, name: str, tasks: List[Task] = None) -> None:
        self.id = milestone_id
        self.name = name
        self.tasks = tasks or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tasks": [t.to_dict() for t in self.tasks],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Milestone:
        tasks = [Task.from_dict(t) for t in data.get("tasks", [])]
        return cls(data["id"], data["name"], tasks)


class Project:
    def __init__(self, project_id: str, name: str, goal: str, milestones: List[Milestone] = None) -> None:
        self.id = project_id
        self.name = name
        self.goal = goal
        self.milestones = milestones or []
        self.status = "active"  # active, completed, failed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "goal": self.goal,
            "milestones": [m.to_dict() for m in self.milestones],
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Project:
        milestones = [Milestone.from_dict(m) for m in data.get("milestones", [])]
        p = cls(data["id"], data["name"], data["goal"], milestones)
        p.status = data.get("status", "active")
        return p


class ProjectOS:
    """Manages project hierarchies, tracks dependencies, risks, and serializes state."""

    def __init__(self) -> None:
        self.projects_file = PROJECTS_FILE
        self.projects: Dict[str, Project] = {}
        self.load_projects()

    def load_projects(self) -> None:
        if not self.projects_file.exists():
            return
        try:
            with open(self.projects_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for pid, pdata in data.items():
                    self.projects[pid] = Project.from_dict(pdata)
            logger.info(f"Loaded {len(self.projects)} projects successfully.")
        except Exception as e:
            logger.error(f"Failed to load projects: {e}")

    def save_projects(self) -> None:
        try:
            self.projects_file.parent.mkdir(parents=True, exist_ok=True)
            data = {pid: p.to_dict() for pid, p in self.projects.items()}
            with open(self.projects_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info("Successfully serialized project states.")
        except Exception as e:
            logger.error(f"Failed to serialize projects: {e}")

    def create_project(self, name: str, goal: str) -> Project:
        pid = f"proj_{name.lower().replace(' ', '_')[:15]}"
        p = Project(pid, name, goal)
        self.projects[pid] = p
        self.save_projects()
        return p

    def add_milestone(self, project_id: str, name: str) -> Optional[Milestone]:
        p = self.projects.get(project_id)
        if not p:
            return None
        mid = f"ms_{len(p.milestones) + 1}"
        m = Milestone(mid, name)
        p.milestones.append(m)
        self.save_projects()
        return m

    def add_task(self, project_id: str, milestone_id: str, name: str, blockers: List[str] = None) -> Optional[Task]:
        p = self.projects.get(project_id)
        if not p:
            return None
        m = next((ms for ms in p.milestones if ms.id == milestone_id), None)
        if not m:
            return None
        tid = f"task_{len(m.tasks) + 1}"
        t = Task(tid, name, blockers=blockers)
        m.tasks.append(t)
        self.save_projects()
        return t

    def update_task_status(self, project_id: str, task_id: str, status: str) -> bool:
        p = self.projects.get(project_id)
        if not p:
            return False
        for ms in p.milestones:
            for t in ms.tasks:
                if t.id == task_id:
                    t.status = status
                    
                    # Cascade checks
                    if status == "failed":
                        t.risk_level = "high"
                    elif status == "done":
                        t.risk_level = "low"
                        
                    self.save_projects()
                    return True
        return False

    def get_progress(self, project_id: str) -> float:
        """Calculate percentage completion rate of tasks in project."""
        p = self.projects.get(project_id)
        if not p:
            return 0.0
        total = 0
        done = 0
        for ms in p.milestones:
            for t in ms.tasks:
                total += 1
                if t.status == "done":
                    done += 1
        if total == 0:
            return 100.0
        return round((done / total) * 100.0, 1)

    def identify_risks(self, project_id: str) -> List[str]:
        """Scan project for blocking tasks, failures, or circular dependencies."""
        p = self.projects.get(project_id)
        if not p:
            return []
        
        risks = []
        task_map = {}
        for ms in p.milestones:
            for t in ms.tasks:
                task_map[t.id] = t

        for ms in p.milestones:
            for t in ms.tasks:
                if t.status == "failed":
                    risks.append(f"⚠️ Task '{t.name}' (ID: {t.id}) has FAILED.")
                
                # Check blockers status
                for blocker_id in t.blockers:
                    blocker_task = task_map.get(blocker_id)
                    if blocker_task and blocker_task.status in ("failed", "stale"):
                        risks.append(
                            f"🚨 Task '{t.name}' is blocked by failed Task '{blocker_task.name}'."
                        )
                        t.risk_level = "high"

        return risks
