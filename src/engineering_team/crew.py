from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from pydantic import BaseModel
from typing import List, Optional
import os

class ClassSpec(BaseModel):
    class_name: str
    summary: str

class ModuleSpec(BaseModel):
    module_name: str
    classes: List[ClassSpec]
    notes: Optional[str] = ""

class DesignPlan(BaseModel):
    system_name: str
    modules: List[ModuleSpec]

def validate_plan_guardrail(output):
    plan = output.model_dump() if hasattr(output, "model_dump") else output
    modules = plan.get("modules", [])
    assert modules, "Plan contains no modules."
    for m in modules:
        assert m.get("module_name", "").endswith(".py"), "module_name must end with .py"
        assert m.get("classes"), f"{m.get('module_name','<unknown>')} must define at least one class."
    return output

@CrewBase
class EngineeringTeam:
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    @agent
    def engineering_lead(self) -> Agent:
        return Agent(config=self.agents_config['engineering_lead'], verbose=True)

    @agent
    def backend_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['backend_engineer'],
            verbose=True,
            allow_code_execution=True,
            code_execution_mode="safe",
            max_execution_time=500,
            max_retry_limit=3
        )

    @agent
    def frontend_engineer(self) -> Agent:
        return Agent(config=self.agents_config['frontend_engineer'], verbose=True)

    @agent
    def test_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['test_engineer'],
            verbose=True,
            allow_code_execution=True,
            code_execution_mode="safe",
            max_execution_time=500,
            max_retry_limit=3
        )

    # Phase 1: design only (structured output)
    @task
    def design_task(self) -> Task:
        return Task(
            config=self.tasks_config['design_task'],
            output_pydantic=DesignPlan,
        )

    # Helper: build the dynamic tasks list for a given plan
    def build_dynamic_tasks(self, plan: DesignPlan) -> List[Task]:
        tasks: List[Task] = []
        for m in plan.modules:
            mod = m.module_name
            class_names = ", ".join(c.class_name for c in m.classes)

            tasks.append(Task(
                description=f"Implement module {mod} with classes: {class_names}. "
                            f"Follow the design plan precisely. Output ONLY raw Python.",
                expected_output="Valid Python file only, no markdown.",
                agent=self.backend_engineer(),
                # We can include the design summary inline to avoid referencing another Task:
                context=[],  # optional
                output_file=os.path.join("output", mod)
            ))

            tasks.append(Task(
                description=f"Write unit tests for {mod}.",
                expected_output="Valid Python file only.",
                agent=self.test_engineer(),
                context=[tasks[-1]],  # depends on the code task we just created
                output_file=os.path.join("output", f"test_{mod}")
            ))

        # One UI that imports all modules
        imports = ", ".join(m.module_name for m in plan.modules)
        tasks.append(Task(
            description=("Create a minimal Gradio demo app (app.py) that imports and demonstrates "
                         f"these modules: {imports}. Keep it very simple."),
            expected_output="Valid Python file only.",
            agent=self.frontend_engineer(),
            context=[t for t in tasks if t.output_file and t.output_file.endswith(".py")],
            output_file=os.path.join("output", "app.py")
        ))
        return tasks

    @crew
    def crew(self) -> Crew:
        # We return a Crew with ONLY the design task.
        # Your UI will:
        #   1) run this crew (design only),
        #   2) read the structured plan from design_task.output.pydantic,
        #   3) create a second Crew programmatically with the dynamic tasks,
        #   4) run it to generate all modules/tests/frontend.
        return Crew(
            agents=self.agents,
            tasks=[self.design_task()],
            process=Process.sequential,
            verbose=True,
        )
