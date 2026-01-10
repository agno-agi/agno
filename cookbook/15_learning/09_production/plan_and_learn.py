"""
Plan and Learn Integration
==========================

Integrating learning with planning and task execution for
sophisticated agentic workflows.

Key Concepts:
- Learning from task execution
- Plan improvement over time
- Error pattern learning
- Success pattern extraction

Run: python -m cookbook.production.plan_and_learn
"""

from datetime import datetime
from typing import Any, Dict, List

from agno.learn import LearningMachine, LearningMode

# =============================================================================
# ARCHITECTURE OVERVIEW
# =============================================================================


def show_architecture():
    """Show plan and learn architecture."""

    print("=" * 60)
    print("PLAN AND LEARN ARCHITECTURE")
    print("=" * 60)

    print("""
    Agents that learn from their own execution:
    
    ┌─────────────────────────────────────────────────────────┐
    │                   USER REQUEST                          │
    └───────────────────────┬─────────────────────────────────┘
                            │
                            ▼
    ┌─────────────────────────────────────────────────────────┐
    │                    PLANNER                              │
    │  ┌─────────────────────────────────────────────────┐   │
    │  │  Input: User request + context                   │   │
    │  │  Retrieves: Past similar plans, success patterns │   │
    │  │  Output: Execution plan                          │   │
    │  └─────────────────────────────────────────────────┘   │
    └───────────────────────┬─────────────────────────────────┘
                            │
                            ▼
    ┌─────────────────────────────────────────────────────────┐
    │                   EXECUTOR                              │
    │  ┌─────────────────────────────────────────────────┐   │
    │  │  Executes plan steps                             │   │
    │  │  Handles errors with learned patterns            │   │
    │  │  Records: Success/failure, timing, resources     │   │
    │  └─────────────────────────────────────────────────┘   │
    └───────────────────────┬─────────────────────────────────┘
                            │
                            ▼
    ┌─────────────────────────────────────────────────────────┐
    │                   LEARNER                               │
    │  ┌─────────────────────────────────────────────────┐   │
    │  │  Analyzes execution results                      │   │
    │  │  Extracts: Patterns, errors, improvements        │   │
    │  │  Updates: Knowledge stores                       │   │
    │  └─────────────────────────────────────────────────┘   │
    └─────────────────────────────────────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │    KNOWLEDGE STORES     │
              │  • Plan templates       │
              │  • Error patterns       │
              │  • Success patterns     │
              │  • Domain knowledge     │
              └─────────────────────────┘
    """)


# =============================================================================
# LEARNING-ENHANCED PLANNER
# =============================================================================


def demo_learning_planner():
    """Show planner that uses learned knowledge."""

    print("\n" + "=" * 60)
    print("LEARNING-ENHANCED PLANNER")
    print("=" * 60)

    print("""
    Planner retrieves relevant knowledge before planning:
    """)

    print("\n💻 IMPLEMENTATION:")
    print("-" * 40)
    print("""
    class LearningPlanner:
        '''Planner that uses learned knowledge.'''
        
        def __init__(self, llm, learning_machine):
            self.llm = llm
            self.machine = learning_machine
        
        async def create_plan(self, task: str, context: Dict) -> Dict:
            '''Create a plan using learned knowledge.'''
            
            # 1. Retrieve relevant past knowledge
            knowledge = await self._retrieve_knowledge(task)
            
            # 2. Build context-aware prompt
            prompt = self._build_planning_prompt(
                task=task,
                context=context,
                similar_plans=knowledge["similar_plans"],
                success_patterns=knowledge["success_patterns"],
                known_pitfalls=knowledge["error_patterns"]
            )
            
            # 3. Generate plan
            plan = await self.llm.generate(prompt)
            
            # 4. Validate against known issues
            validated_plan = self._validate_plan(plan, knowledge["error_patterns"])
            
            return validated_plan
        
        async def _retrieve_knowledge(self, task: str) -> Dict:
            '''Retrieve relevant knowledge for planning.'''
            
            # Search for similar past tasks
            similar_plans = await self.machine.learned_knowledge.search(
                query=f"plan for: {task}",
                filter={"type": "plan_template"},
                limit=3
            )
            
            # Get success patterns for this domain
            success_patterns = await self.machine.learned_knowledge.search(
                query=f"success pattern: {task}",
                filter={"type": "success_pattern"},
                limit=5
            )
            
            # Get known error patterns to avoid
            error_patterns = await self.machine.learned_knowledge.search(
                query=f"error pitfall: {task}",
                filter={"type": "error_pattern"},
                limit=5
            )
            
            return {
                "similar_plans": similar_plans,
                "success_patterns": success_patterns,
                "error_patterns": error_patterns
            }
        
        def _build_planning_prompt(self, task, context, similar_plans, 
                                   success_patterns, known_pitfalls):
            '''Build prompt with learned context.'''
            
            prompt = f'''Create a plan for: {task}
            
Context: {context}

Similar successful plans:
{self._format_plans(similar_plans)}

Success patterns to follow:
{self._format_patterns(success_patterns)}

Known pitfalls to avoid:
{self._format_patterns(known_pitfalls)}

Create a detailed plan that:
1. Follows successful patterns from similar tasks
2. Avoids known pitfalls
3. Is appropriate for the given context
'''
            return prompt
    """)


# =============================================================================
# EXECUTION LEARNING
# =============================================================================


def demo_execution_learning():
    """Show learning from execution."""

    print("\n" + "=" * 60)
    print("EXECUTION LEARNING")
    print("=" * 60)

    print("""
    Learn from every execution:
    
    ┌─────────────────────────────────────────────────────────┐
    │              EXECUTION RECORD                           │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  task: "Deploy new feature"                             │
    │  plan_id: "plan_123"                                    │
    │  started_at: "2024-01-15T10:00:00"                      │
    │  completed_at: "2024-01-15T10:15:00"                    │
    │  status: "success"                                      │
    │                                                         │
    │  steps:                                                 │
    │    [1] run_tests: success (2min)                        │
    │    [2] build_artifact: success (5min)                   │
    │    [3] deploy_staging: success (3min)                   │
    │    [4] run_smoke_tests: success (2min)                  │
    │    [5] deploy_prod: success (3min)                      │
    │                                                         │
    │  resources_used:                                        │
    │    cpu: 4 cores                                         │
    │    memory: 8GB                                          │
    │    api_calls: 15                                        │
    │                                                         │
    │  learned_insights:                                      │
    │    - "Smoke tests caught config issue before prod"      │
    │    - "Build step could be parallelized"                 │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n💻 IMPLEMENTATION:")
    print("-" * 40)
    print("""
    class ExecutionLearner:
        '''Learn from task execution.'''
        
        def __init__(self, learning_machine):
            self.machine = learning_machine
        
        async def record_execution(self, execution: Dict):
            '''Record and learn from an execution.'''
            
            # Store raw execution record
            await self.machine.entity_memory.put(
                key=f"execution:{execution['id']}",
                value={
                    "type": "execution_record",
                    "task": execution["task"],
                    "status": execution["status"],
                    "duration": execution["duration"],
                    "steps": execution["steps"],
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            # Extract learnings based on outcome
            if execution["status"] == "success":
                await self._learn_from_success(execution)
            else:
                await self._learn_from_failure(execution)
        
        async def _learn_from_success(self, execution: Dict):
            '''Extract patterns from successful execution.'''
            
            # If this plan consistently succeeds, save as template
            similar_executions = await self._get_similar_executions(
                execution["task"]
            )
            success_rate = self._calculate_success_rate(similar_executions)
            
            if success_rate > 0.8 and len(similar_executions) >= 3:
                # This plan is reliable - save as template
                await self.machine.learned_knowledge.put(
                    key=f"plan_template:{execution['plan_id']}",
                    value={
                        "type": "plan_template",
                        "task_pattern": execution["task"],
                        "plan": execution["plan"],
                        "success_rate": success_rate,
                        "avg_duration": self._avg_duration(similar_executions),
                        "confidence": 0.9
                    }
                )
            
            # Extract success patterns
            patterns = await self._extract_success_patterns(execution)
            for pattern in patterns:
                await self.machine.learned_knowledge.put(
                    key=f"success_pattern:{hash(pattern['description'])}",
                    value={
                        "type": "success_pattern",
                        "description": pattern["description"],
                        "task_domain": execution["task_domain"],
                        "confidence": pattern["confidence"]
                    }
                )
        
        async def _learn_from_failure(self, execution: Dict):
            '''Extract error patterns from failed execution.'''
            
            # Identify where failure occurred
            failed_step = self._find_failed_step(execution["steps"])
            
            # Check if this is a recurring failure
            similar_failures = await self._get_similar_failures(
                execution["task"],
                failed_step
            )
            
            if len(similar_failures) >= 2:
                # Recurring issue - save as error pattern
                await self.machine.learned_knowledge.put(
                    key=f"error_pattern:{hash(failed_step['error'])}",
                    value={
                        "type": "error_pattern",
                        "description": failed_step["error"],
                        "task_domain": execution["task_domain"],
                        "step_type": failed_step["type"],
                        "frequency": len(similar_failures),
                        "suggested_fix": self._suggest_fix(similar_failures)
                    }
                )
    """)


# =============================================================================
# ERROR RECOVERY LEARNING
# =============================================================================


def demo_error_recovery():
    """Show learning error recovery strategies."""

    print("\n" + "=" * 60)
    print("ERROR RECOVERY LEARNING")
    print("=" * 60)

    print("""
    Learn and apply error recovery strategies:
    
    ┌─────────────────────────────────────────────────────────┐
    │              ERROR RECOVERY FLOW                        │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  Error Occurs                                           │
    │       │                                                 │
    │       ▼                                                 │
    │  ┌─────────────────────────────────────┐               │
    │  │  Search learned error patterns      │               │
    │  └──────────────────┬──────────────────┘               │
    │                     │                                   │
    │       ┌─────────────┴─────────────┐                    │
    │       │                           │                    │
    │       ▼                           ▼                    │
    │  [Pattern Found]           [No Pattern]                │
    │       │                           │                    │
    │       ▼                           ▼                    │
    │  Apply learned fix          Try generic recovery       │
    │       │                           │                    │
    │       │                           │                    │
    │       └─────────────┬─────────────┘                    │
    │                     │                                   │
    │                     ▼                                   │
    │            Record outcome                               │
    │            Learn from result                            │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n💻 IMPLEMENTATION:")
    print("-" * 40)
    print("""
    class AdaptiveErrorHandler:
        '''Error handler that learns recovery strategies.'''
        
        def __init__(self, learning_machine):
            self.machine = learning_machine
            self.recovery_attempts = {}
        
        async def handle_error(self, error: Exception, context: Dict) -> Dict:
            '''Handle error using learned strategies.'''
            
            error_sig = self._get_error_signature(error)
            
            # Search for known recovery strategies
            strategies = await self.machine.learned_knowledge.search(
                query=f"recovery for: {error_sig}",
                filter={"type": "recovery_strategy"},
                limit=3
            )
            
            if strategies:
                # Try learned strategy
                best_strategy = strategies[0]
                result = await self._apply_strategy(best_strategy, context)
                
                # Record outcome
                await self._record_recovery_attempt(
                    error=error,
                    strategy=best_strategy,
                    success=result["success"]
                )
                
                return result
            else:
                # No learned strategy - try generic and learn
                result = await self._generic_recovery(error, context)
                
                if result["success"]:
                    # Save new recovery strategy
                    await self.machine.learned_knowledge.put(
                        key=f"recovery:{error_sig}",
                        value={
                            "type": "recovery_strategy",
                            "error_signature": error_sig,
                            "strategy": result["strategy_used"],
                            "success_rate": 1.0,
                            "attempts": 1
                        }
                    )
                
                return result
        
        async def _record_recovery_attempt(self, error, strategy, success: bool):
            '''Update strategy success rate.'''
            
            # Get current stats
            current = await self.machine.learned_knowledge.get(strategy["key"])
            
            if current:
                attempts = current["attempts"] + 1
                successes = current["success_rate"] * current["attempts"]
                if success:
                    successes += 1
                new_rate = successes / attempts
                
                # Update strategy
                await self.machine.learned_knowledge.put(
                    key=strategy["key"],
                    value={
                        **current,
                        "success_rate": new_rate,
                        "attempts": attempts
                    }
                )
    """)


# =============================================================================
# PLAN IMPROVEMENT
# =============================================================================


def demo_plan_improvement():
    """Show continuous plan improvement."""

    print("\n" + "=" * 60)
    print("PLAN IMPROVEMENT OVER TIME")
    print("=" * 60)

    print("""
    Plans improve through execution feedback:
    
    ┌─────────────────────────────────────────────────────────┐
    │              IMPROVEMENT CYCLE                          │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  Version 1.0 (Initial)                                  │
    │  ├─ Steps: A → B → C → D                                │
    │  ├─ Avg time: 15 min                                    │
    │  └─ Success rate: 70%                                   │
    │                                                         │
    │       │ Learning: Step B often fails, retry helps       │
    │       ▼                                                 │
    │                                                         │
    │  Version 1.1 (Add retry)                                │
    │  ├─ Steps: A → B (retry 3x) → C → D                     │
    │  ├─ Avg time: 16 min                                    │
    │  └─ Success rate: 85%                                   │
    │                                                         │
    │       │ Learning: C and D can run in parallel           │
    │       ▼                                                 │
    │                                                         │
    │  Version 1.2 (Parallelize)                              │
    │  ├─ Steps: A → B (retry) → [C || D]                     │
    │  ├─ Avg time: 12 min                                    │
    │  └─ Success rate: 85%                                   │
    │                                                         │
    │       │ Learning: Pre-check prevents most B failures    │
    │       ▼                                                 │
    │                                                         │
    │  Version 1.3 (Pre-check)                                │
    │  ├─ Steps: PreCheck → A → B → [C || D]                  │
    │  ├─ Avg time: 10 min                                    │
    │  └─ Success rate: 95%                                   │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n💻 IMPLEMENTATION:")
    print("-" * 40)
    print("""
    class PlanEvolver:
        '''Evolves plans based on execution data.'''
        
        def __init__(self, learning_machine):
            self.machine = learning_machine
        
        async def suggest_improvements(self, plan_id: str) -> List[Dict]:
            '''Analyze executions and suggest improvements.'''
            
            # Get execution history for this plan
            executions = await self.machine.entity_memory.search(
                query=f"execution plan:{plan_id}",
                filter={"type": "execution_record"},
                limit=50
            )
            
            improvements = []
            
            # Analyze failure points
            failure_analysis = self._analyze_failures(executions)
            for step, failure_rate in failure_analysis.items():
                if failure_rate > 0.2:
                    improvements.append({
                        "type": "add_retry",
                        "step": step,
                        "reason": f"Step fails {failure_rate:.0%} of the time",
                        "suggestion": f"Add retry logic with exponential backoff"
                    })
            
            # Analyze parallelization opportunities
            timing_data = self._analyze_timing(executions)
            parallel_candidates = self._find_parallel_opportunities(timing_data)
            for steps in parallel_candidates:
                improvements.append({
                    "type": "parallelize",
                    "steps": steps,
                    "reason": "Steps have no dependencies",
                    "estimated_time_saved": self._estimate_savings(steps, timing_data)
                })
            
            # Analyze pre-check opportunities
            precheck_candidates = self._find_precheck_opportunities(executions)
            for check in precheck_candidates:
                improvements.append({
                    "type": "add_precheck",
                    "check": check["description"],
                    "reason": f"Would prevent {check['preventable_failures']} failures",
                    "estimated_success_rate_improvement": check["improvement"]
                })
            
            return improvements
        
        async def apply_improvement(self, plan_id: str, improvement: Dict):
            '''Apply an improvement and create new plan version.'''
            
            current_plan = await self.machine.entity_memory.get(f"plan:{plan_id}")
            
            # Apply the improvement
            if improvement["type"] == "add_retry":
                new_plan = self._add_retry_to_step(
                    current_plan,
                    improvement["step"]
                )
            elif improvement["type"] == "parallelize":
                new_plan = self._parallelize_steps(
                    current_plan,
                    improvement["steps"]
                )
            elif improvement["type"] == "add_precheck":
                new_plan = self._add_precheck(
                    current_plan,
                    improvement["check"]
                )
            
            # Save as new version
            new_version = current_plan["version"] + 1
            await self.machine.entity_memory.put(
                key=f"plan:{plan_id}:v{new_version}",
                value={
                    **new_plan,
                    "version": new_version,
                    "based_on": plan_id,
                    "improvement_applied": improvement
                }
            )
            
            return new_version
    """)


# =============================================================================
# FULL INTEGRATION
# =============================================================================


def demo_full_integration():
    """Show full plan-and-learn system."""

    print("\n" + "=" * 60)
    print("FULL INTEGRATION")
    print("=" * 60)

    print("""
    Complete plan-and-learn agent:
    """)

    print("\n💻 IMPLEMENTATION:")
    print("-" * 40)
    print("""
    class PlanAndLearnAgent:
        '''Agent that plans, executes, and learns.'''
        
        def __init__(self, llm, tools):
            self.llm = llm
            self.tools = tools
            
            # Initialize learning machine
            self.machine = LearningMachine(
                user_profile=False,  # Agent doesn't need user profile
                session_context=True,  # Track current execution
                entity_memory={
                    "namespace": "agent:executions"
                },
                learned_knowledge={
                    "namespace": "agent:knowledge"
                }
            )
            
            # Initialize components
            self.planner = LearningPlanner(llm, self.machine)
            self.executor = Executor(tools)
            self.learner = ExecutionLearner(self.machine)
            self.error_handler = AdaptiveErrorHandler(self.machine)
        
        async def execute_task(self, task: str, context: Dict = None):
            '''Plan, execute, and learn from a task.'''
            
            # 1. Create plan using learned knowledge
            plan = await self.planner.create_plan(task, context or {})
            
            # 2. Execute with error handling
            execution_record = {
                "id": generate_id(),
                "task": task,
                "plan": plan,
                "started_at": datetime.now(),
                "steps": []
            }
            
            try:
                for step in plan["steps"]:
                    step_result = await self._execute_step(step)
                    execution_record["steps"].append(step_result)
                    
                    if not step_result["success"]:
                        # Try error recovery
                        recovery = await self.error_handler.handle_error(
                            step_result["error"],
                            {"step": step, "plan": plan}
                        )
                        
                        if not recovery["success"]:
                            execution_record["status"] = "failed"
                            break
                else:
                    execution_record["status"] = "success"
                    
            except Exception as e:
                execution_record["status"] = "failed"
                execution_record["error"] = str(e)
            
            execution_record["completed_at"] = datetime.now()
            execution_record["duration"] = (
                execution_record["completed_at"] - 
                execution_record["started_at"]
            ).total_seconds()
            
            # 3. Learn from execution
            await self.learner.record_execution(execution_record)
            
            return execution_record
        
        async def _execute_step(self, step: Dict) -> Dict:
            '''Execute a single step with monitoring.'''
            started = datetime.now()
            
            try:
                result = await self.executor.run(step)
                return {
                    "step": step["name"],
                    "success": True,
                    "result": result,
                    "duration": (datetime.now() - started).total_seconds()
                }
            except Exception as e:
                return {
                    "step": step["name"],
                    "success": False,
                    "error": e,
                    "duration": (datetime.now() - started).total_seconds()
                }
    
    # Usage
    agent = PlanAndLearnAgent(llm=get_llm(), tools=get_tools())
    
    # Execute task - agent learns from each execution
    result = await agent.execute_task(
        task="Deploy application to production",
        context={"environment": "prod", "version": "2.1.0"}
    )
    
    # Over time, the agent:
    # - Builds library of successful plan templates
    # - Learns error patterns and recovery strategies
    # - Improves plans based on execution data
    # - Handles new errors using learned patterns
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("🎯 PLAN AND LEARN INTEGRATION")
    print("=" * 60)
    print("Sophisticated planning with continuous learning")
    print()

    show_architecture()
    demo_learning_planner()
    demo_execution_learning()
    demo_error_recovery()
    demo_plan_improvement()
    demo_full_integration()

    print("\n" + "=" * 60)
    print("✅ Plan and learn guide complete!")
    print("=" * 60)
