from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel
from typing import List, Optional
import os

# --- 数据结构定义 (用于 Phase 1 的结构化输出) ---

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

# --- 核心 LLM 配置 ---
# 确保你已经安装了: pip install langchain-google-genai
# 确保设置了环境变量: GOOGLE_API_KEY
gemini_llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash", 
    temperature=0.2
)

@CrewBase
class EngineeringTeam:
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    # --- Agent 定义 (强制覆盖 YAML 中的 OpenAI 配置) ---

    @agent
    def engineering_lead(self) -> Agent:
        return Agent(
            config=self.agents_config['engineering_lead'], 
            llm=gemini_llm, 
            verbose=True
        )

    @agent
    def backend_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['backend_engineer'],
            llm=gemini_llm,
            verbose=True,
            allow_code_execution=True, # 允许代码执行
            max_execution_time=500,
            max_retry_limit=3
        )

    @agent
    def frontend_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['frontend_engineer'], 
            llm=gemini_llm,
            verbose=True
        )

    @agent
    def test_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['test_engineer'],
            llm=gemini_llm,
            verbose=True,
            allow_code_execution=True,
            max_execution_time=500,
            max_retry_limit=3
        )

    # --- 任务定义 ---

    # 阶段 1：生成系统设计蓝图
    @task
    def design_task(self) -> Task:
        return Task(
            config=self.tasks_config['design_task'],
            output_pydantic=DesignPlan, # 这里会强制 AI 输出 JSON 格式
        )

    # 动态任务构建器：根据阶段 1 的 JSON 生成后续的所有开发任务
    def build_dynamic_tasks(self, plan: DesignPlan) -> List[Task]:
        tasks: List[Task] = []
        
        # 确保输出目录存在
        if not os.path.exists("output"):
            os.makedirs("output")

        for m in plan.modules:
            mod = m.module_name
            class_names = ", ".join(c.class_name for c in m.classes)

            # 为每个模块创建一个开发任务
            code_task = Task(
                description=f"Implement module {mod} with classes: {class_names}. "
                            f"Follow the design plan precisely. Output ONLY raw Python.",
                expected_output="Valid Python file only, no markdown.",
                agent=self.backend_engineer(),
                output_file=os.path.join("output", mod)
            )
            tasks.append(code_task)

            # 为每个模块创建一个测试任务
            tasks.append(Task(
                description=f"Write unit tests for {mod}.",
                expected_output="Valid Python file only.",
                agent=self.test_engineer(),
                context=[code_task], # 依赖于刚生成的代码
                output_file=os.path.join("output", f"test_{mod}")
            )
            )

        # 创建一个 Gradio 前端 app.py，整合所有模块
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
        # 这个 Crew 默认只运行设计任务
        return Crew(
            agents=self.agents,
            tasks=[self.design_task()],
            process=Process.sequential,
            verbose=True,
        )