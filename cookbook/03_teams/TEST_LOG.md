# Test Log: cookbook/03_teams


### 01_quickstart/01_basic_coordination.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### 01_quickstart/02_respond_directly_router_team.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/01_quickstart/02_respond_directly_router_team.py`.

**Result:** Executed successfully.

---

### 01_quickstart/03_delegate_to_all_members.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/01_quickstart/03_delegate_to_all_members.py`.

**Result:** Executed successfully.

---

### 01_quickstart/04_respond_directly_with_history.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/01_quickstart/04_respond_directly_with_history.py`.

**Result:** Executed successfully.

---

### 01_quickstart/05_team_history.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/01_quickstart/05_team_history.py", line 33, in <module>
    multi_lingual_q_and_a_team = Team(
                                 ^^^^^
TypeError: Team.__init__() got an unexpected keyword argument 'pass_user_input_to_members'

---

### 01_quickstart/06_history_of_members.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/01_quickstart/06_history_of_members.py`.

**Result:** Executed successfully.

---

### 01_quickstart/07_share_member_interactions.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/01_quickstart/07_share_member_interactions.py`.

**Result:** Executed successfully.

---

### 01_quickstart/08_concurrent_member_agents.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/01_quickstart/08_concurrent_member_agents.py`.

**Result:** Executed successfully.

---

### 01_quickstart/09_caching.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/01_quickstart/09_caching.py`.

**Result:** Executed successfully.

---

### 01_quickstart/broadcast_mode.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/01_quickstart/broadcast_mode.py`.

**Result:** Executed successfully.

---

### 01_quickstart/nested_teams.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/01_quickstart/nested_teams.py`.

**Result:** Executed successfully.

---

### 01_quickstart/task_mode.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/01_quickstart/task_mode.py`.

**Result:** Executed successfully.

---

### context_compression/tool_call_compression.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/10_context_compression/tool_call_compression.py`.

**Result:** Executed successfully.

---

### context_compression/tool_call_compression_with_manager.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/10_context_compression/tool_call_compression_with_manager.py`.

**Result:** Executed successfully.

---

### context_management/additional_context.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/09_context_management/additional_context.py`.

**Result:** Executed successfully.

---

### context_management/custom_system_message.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/09_context_management/custom_system_message.py`.

**Result:** Executed successfully.

---

### context_management/few_shot_learning.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/09_context_management/few_shot_learning.py`.

**Result:** Executed successfully.

---

### context_management/filter_tool_calls_from_history.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/09_context_management/filter_tool_calls_from_history.py`.

**Result:** Executed successfully.

---

### context_management/introduction.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/09_context_management/introduction.py`.

**Result:** Executed successfully.

---

### context_management/location_context.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/09_context_management/location_context.py`.

**Result:** Executed successfully.

---

### dependencies/dependencies_in_context.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/17_dependencies/dependencies_in_context.py`.

**Result:** Executed successfully.

---

### dependencies/dependencies_in_tools.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/17_dependencies/dependencies_in_tools.py`.

**Result:** Executed successfully.

---

### dependencies/dependencies_to_members.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/17_dependencies/dependencies_to_members.py`.

**Result:** Executed successfully.

---

### distributed_rag/01_distributed_rag_pgvector.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/15_distributed_rag/01_distributed_rag_pgvector.py`.

**Result:** Executed successfully.

---

### distributed_rag/02_distributed_rag_lancedb.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 168, in __init__
    import tantivy  # noqa: F401
    ^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'tantivy'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/15_distributed_rag/02_distributed_rag_lancedb.py", line 30, in <module>
    vector_db=LanceDb(
              ^^^^^^^^
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 170, in __init__
    raise ImportError(
ImportError: Please install tantivy-py `pip install tantivy` to use the full text search feature.

---

### distributed_rag/03_distributed_rag_with_reranking.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 168, in __init__
    import tantivy  # noqa: F401
    ^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'tantivy'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/15_distributed_rag/03_distributed_rag_with_reranking.py", line 23, in <module>
    vector_db=LanceDb(
              ^^^^^^^^
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 170, in __init__
    raise ImportError(
ImportError: Please install tantivy-py `pip install tantivy` to use the full text search feature.

---

### guardrails/openai_moderation.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/18_guardrails/openai_moderation.py`.

**Result:** Executed successfully.

---

### guardrails/pii_detection.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/18_guardrails/pii_detection.py`.

**Result:** Executed successfully.

---

### guardrails/prompt_injection.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/18_guardrails/prompt_injection.py`.

**Result:** Executed successfully.

---

### hooks/post_hook_output.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### hooks/pre_hook_input.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### hooks/stream_hook.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/13_hooks/stream_hook.py`.

**Result:** Executed successfully.

---

### human_in_the_loop/confirmation_rejected.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### human_in_the_loop/confirmation_rejected_stream.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### human_in_the_loop/confirmation_required.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/20_human_in_the_loop/confirmation_required.py`.

**Result:** Executed successfully.

---

### human_in_the_loop/confirmation_required_async.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### human_in_the_loop/confirmation_required_async_stream.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### human_in_the_loop/confirmation_required_stream.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### human_in_the_loop/external_tool_execution.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/20_human_in_the_loop/external_tool_execution.py`.

**Result:** Executed successfully.

---

### human_in_the_loop/external_tool_execution_stream.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### human_in_the_loop/team_tool_confirmation.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### human_in_the_loop/team_tool_confirmation_stream.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### human_in_the_loop/user_input_required.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/20_human_in_the_loop/user_input_required.py`.

**Result:** Executed successfully.

---

### human_in_the_loop/user_input_required_stream.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### knowledge/01_team_with_knowledge.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 168, in __init__
    import tantivy  # noqa: F401
    ^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'tantivy'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/05_knowledge/01_team_with_knowledge.py", line 26, in <module>
    vector_db=LanceDb(
              ^^^^^^^^
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 170, in __init__
    raise ImportError(
ImportError: Please install tantivy-py `pip install tantivy` to use the full text search feature.

---

### knowledge/02_team_with_knowledge_filters.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### knowledge/03_team_with_agentic_knowledge_filters.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### knowledge/04_team_with_custom_retriever.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/05_knowledge/04_team_with_custom_retriever.py`.

**Result:** Executed successfully.

---

### knowledge/05_team_update_knowledge.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/05_knowledge/05_team_update_knowledge.py`.

**Result:** Executed successfully.

---

### learning/01_team_always_learn.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### learning/02_team_configured_learning.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### learning/03_team_entity_memory.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### learning/04_team_session_planning.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### learning/05_team_learned_knowledge.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### learning/06_team_decision_log.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### memory/01_team_with_memory_manager.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/06_memory/01_team_with_memory_manager.py`.

**Result:** Executed successfully.

---

### memory/02_team_with_agentic_memory.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/06_memory/02_team_with_agentic_memory.py`.

**Result:** Executed successfully.

---

### memory/03_memories_in_context.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/06_memory/03_memories_in_context.py`.

**Result:** Executed successfully.

---

### memory/learning_machine.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/06_memory/learning_machine.py`.

**Result:** Executed successfully.

---

### metrics/01_team_metrics.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/22_metrics/01_team_metrics.py`.

**Result:** Executed successfully.

---

### modes/broadcast/01_basic.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/broadcast/02_debate.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/broadcast/03_research_sweep.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/coordinate/01_basic.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/coordinate/02_with_tools.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/coordinate/03_structured_output.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline,import_after_first_section_banner | Run: completed

---

### modes/route/01_basic.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/route/02_specialist_router.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/route/03_with_fallback.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/tasks/01_basic.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/tasks/02_parallel.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/tasks/03_dependencies.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/tasks/04_basic_task_mode.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/tasks/05_parallel_tasks.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/tasks/06_task_mode_with_tools.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/tasks/07_async_task_mode.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/tasks/08_dependency_chain.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/tasks/09_custom_tools.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### modes/tasks/10_multi_run_session.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### multimodal/audio_sentiment_analysis.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/19_multimodal/audio_sentiment_analysis.py`.

**Result:** Executed successfully.

---

### multimodal/audio_to_text.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/19_multimodal/audio_to_text.py`.

**Result:** Executed successfully.

---

### multimodal/generate_image_with_team.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/19_multimodal/generate_image_with_team.py`.

**Result:** Executed successfully.

---

### multimodal/image_to_image_transformation.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/tools/fal.py", line 17, in <module>
    import fal_client  # type: ignore
    ^^^^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'fal_client'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/19_multimodal/image_to_image_transformation.py", line 11, in <module>
    from agno.tools.fal import FalTools
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/tools/fal.py", line 19, in <module>
    raise ImportError("`fal_client` not installed. Please install using `pip install fal-client`")
ImportError: `fal_client` not installed. Please install using `pip install fal-client`

---

### multimodal/image_to_structured_output.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### multimodal/image_to_text.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/19_multimodal/image_to_text.py`.

**Result:** Executed successfully.

---

### multimodal/media_input_for_tool.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### multimodal/video_caption_generation.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/tools/moviepy_video.py", line 7, in <module>
    from moviepy import ColorClip, CompositeVideoClip, TextClip, VideoFileClip  # type: ignore
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'moviepy'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/19_multimodal/video_caption_generation.py", line 11, in <module>
    from agno.tools.moviepy_video import MoviePyVideoTools
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/tools/moviepy_video.py", line 9, in <module>
    raise ImportError("`moviepy` not installed. Please install using `pip install moviepy ffmpeg`")
ImportError: `moviepy` not installed. Please install using `pip install moviepy ffmpeg`

---

### reasoning/reasoning_multi_purpose_team.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/tools/e2b.py", line 19, in <module>
    from e2b_code_interpreter import Sandbox
ModuleNotFoundError: No module named 'e2b_code_interpreter'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/11_reasoning/reasoning_multi_purpose_team.py", line 18, in <module>
    from agno.tools.e2b import E2BTools
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/tools/e2b.py", line 21, in <module>
    raise ImportError("`e2b_code_interpreter` not installed. Please install using `pip install e2b_code_interpreter`")
ImportError: `e2b_code_interpreter` not installed. Please install using `pip install e2b_code_interpreter`

---

### run_control/background_execution.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### run_control/cancel_run.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/14_run_control/cancel_run.py`.

**Result:** Executed successfully.

---

### run_control/model_inheritance.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/14_run_control/model_inheritance.py`.

**Result:** Executed successfully.

---

### run_control/remote_team.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/14_run_control/remote_team.py`.

**Result:** Executed successfully.

---

### run_control/retries.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/14_run_control/retries.py`.

**Result:** Executed successfully.

---

### search_coordination/01_coordinated_agentic_rag.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 168, in __init__
    import tantivy  # noqa: F401
    ^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'tantivy'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/16_search_coordination/01_coordinated_agentic_rag.py", line 20, in <module>
    vector_db=LanceDb(
              ^^^^^^^^
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 170, in __init__
    raise ImportError(
ImportError: Please install tantivy-py `pip install tantivy` to use the full text search feature.

---

### search_coordination/02_coordinated_reasoning_rag.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 168, in __init__
    import tantivy  # noqa: F401
    ^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'tantivy'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/16_search_coordination/02_coordinated_reasoning_rag.py", line 21, in <module>
    vector_db=LanceDb(
              ^^^^^^^^
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 170, in __init__
    raise ImportError(
ImportError: Please install tantivy-py `pip install tantivy` to use the full text search feature.

---

### search_coordination/03_distributed_infinity_search.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/knowledge/reranker/infinity.py", line 9, in <module>
    from infinity_client import AuthenticatedClient, Client
ModuleNotFoundError: No module named 'infinity_client'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/16_search_coordination/03_distributed_infinity_search.py", line 11, in <module>
    from agno.knowledge.reranker.infinity import InfinityReranker
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/knowledge/reranker/infinity.py", line 13, in <module>
    raise ImportError("infinity_client not installed, please run `pip install infinity_client`")
ImportError: infinity_client not installed, please run `pip install infinity_client`

---

### session/chat_history.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/07_session/chat_history.py`.

**Result:** Executed successfully.

---

### session/custom_session_summary.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/07_session/custom_session_summary.py`.

**Result:** Executed successfully.

---

### session/persistent_session.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/07_session/persistent_session.py`.

**Result:** Executed successfully.

---

### session/search_session_history.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/07_session/search_session_history.py`.

**Result:** Executed successfully.

---

### session/session_options.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: ERROR    Model authentication error from OpenAI API: OPENAI_API_KEY not set.    
         Please set the OPENAI_API_KEY environment variable.                    
ERROR    Error in Team run: OPENAI_API_KEY not set. Please set the              
         OPENAI_API_KEY environment variable.                                   
┏━ Message ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                                              ┃
┃ Tell me a new interesting fact about space                                   ┃
┃                                                                              ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
┏━ Response (0.1s) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                                              ┃
┃ OPENAI_API_KEY not set. Please set the OPENAI_API_KEY environment variable.  ┃
┃                                                                              ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛Interesting Space Facts
ERROR    Model authentication error from OpenAI API: OPENAI_API_KEY not set.    
         Please set the OPENAI_API_KEY environment variable.                    

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/07_session/session_options.py", line 67, in <module>
    renamable_team.set_session_name(autogenerate=True)
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/team/team.py", line 1511, in set_session_name
    return _session.set_session_name(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/team/_session.py", line 329, in set_session_name
    set_session_name_util(
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/utils/agent.py", line 695, in set_session_name_util
    session_name = 

---

### session/session_summary.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/07_session/session_summary.py`.

**Result:** Executed successfully.

---

### session/share_session_with_agent.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/07_session/share_session_with_agent.py`.

**Result:** Executed successfully.

---

### state/agentic_session_state.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/21_state/agentic_session_state.py`.

**Result:** Executed successfully.

---

### state/change_state_on_run.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/21_state/change_state_on_run.py`.

**Result:** Executed successfully.

---

### state/nested_shared_state.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: import_after_first_section_banner | Run: completed

---

### state/overwrite_stored_session_state.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/21_state/overwrite_stored_session_state.py`.

**Result:** Executed successfully.

---

### state/state_sharing.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/21_state/state_sharing.py`.

**Result:** Executed successfully.

---

### streaming/team_events.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/08_streaming/team_events.py`.

**Result:** Executed successfully.

---

### streaming/team_streaming.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/08_streaming/team_streaming.py`.

**Result:** Executed successfully.

---

### structured_input_output/expected_output.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/04_structured_input_output/expected_output.py`.

**Result:** Executed successfully.

---

### structured_input_output/input_formats.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/04_structured_input_output/input_formats.py`.

**Result:** Executed successfully.

---

### structured_input_output/input_schema.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### structured_input_output/json_schema_output.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: ERROR    Model authentication error from OpenAI API: OPENAI_API_KEY not set.    
         Please set the OPENAI_API_KEY environment variable.                    
ERROR    Error in Team run: OPENAI_API_KEY not set. Please set the              
         OPENAI_API_KEY environment variable.                                   

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/04_structured_input_output/json_schema_output.py", line 69, in <module>
    assert isinstance(response.content, dict)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError

---

### structured_input_output/output_model.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/04_structured_input_output/output_model.py`.

**Result:** Executed successfully.

---

### structured_input_output/output_schema_override.py

**Status:** FAIL

**Description:** Validation issue: style, runtime

**Result:** Style: code_before_first_section_banner | Run: ERROR    Model authentication error from OpenAI API: OPENAI_API_KEY not set.    
         Please set the OPENAI_API_KEY environment variable.                    
ERROR    Error in Team run: OPENAI_API_KEY not set. Please set the              
         OPENAI_API_KEY environment variable.                                   

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/04_structured_input_output/output_schema_override.py", line 107, in <module>
    assert isinstance(response.content, PersonSchema)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError

---

### structured_input_output/parser_model.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### structured_input_output/pydantic_input.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### structured_input_output/pydantic_output.py

**Status:** FAIL

**Description:** Validation issue: style, runtime

**Result:** Style: code_before_first_section_banner | Run: ERROR    Model authentication error from OpenAI API: OPENAI_API_KEY not set.    
         Please set the OPENAI_API_KEY environment variable.                    
ERROR    Error in Team run: OPENAI_API_KEY not set. Please set the              
         OPENAI_API_KEY environment variable.                                   

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/04_structured_input_output/pydantic_output.py", line 69, in <module>
    assert isinstance(response.content, StockReport)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError

---

### structured_input_output/response_as_variable.py

**Status:** FAIL

**Description:** Validation issue: style, runtime

**Result:** Style: code_before_first_section_banner | Run: ==================================================
STOCK PRICE ANALYSIS
==================================================
ERROR    Model authentication error from OpenAI API: OPENAI_API_KEY not set.    
         Please set the OPENAI_API_KEY environment variable.                    
ERROR    Error in Team run: OPENAI_API_KEY not set. Please set the              
         OPENAI_API_KEY environment variable.                                   

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/04_structured_input_output/response_as_variable.py", line 91, in <module>
    assert isinstance(stock_response.content, StockAnalysis)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError

---

### structured_input_output/structured_output_streaming.py

**Status:** FAIL

**Description:** Validation issue: style, runtime

**Result:** Style: code_before_first_section_banner | Run: ERROR    Model authentication error from OpenAI API: OPENAI_API_KEY not set.    
         Please set the OPENAI_API_KEY environment variable.                    
ERROR    Error in Team run: OPENAI_API_KEY not set. Please set the              
         OPENAI_API_KEY environment variable.                                   

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/04_structured_input_output/structured_output_streaming.py", line 115, in <module>
    assert isinstance(run_response.content, StockReport)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError

---

### tools/async_tools.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/tools/agentql.py", line 8, in <module>
    import agentql
ModuleNotFoundError: No module named 'agentql'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/03_tools/async_tools.py", line 14, in <module>
    from agno.tools.agentql import AgentQLTools
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/tools/agentql.py", line 11, in <module>
    raise ImportError("`agentql` not installed. Please install using `pip install agentql`")
ImportError: `agentql` not installed. Please install using `pip install agentql`

---

### tools/custom_tools.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### tools/member_information.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/03_tools/member_information.py`.

**Result:** Executed successfully.

---

### tools/member_tool_hooks.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/03_tools/member_tool_hooks.py`.

**Result:** Executed successfully.

---

### tools/tool_call_limit.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### tools/tool_choice.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### tools/tool_hooks.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/03_tools/tool_hooks.py`.

**Result:** Executed successfully.

---
