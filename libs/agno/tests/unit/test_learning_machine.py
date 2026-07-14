from unittest.mock import MagicMock

from agno.agent._init import set_learning_machine
from agno.agent.agent import Agent
from agno.learn.config import LearnedKnowledgeConfig, LearningMode
from agno.learn.machine import LearningMachine


def _mock_knowledge():
    kb = MagicMock()
    kb.search.return_value = []
    return kb


# ---------------------------------------------------------------------------
# LearningMachine.requires_history
# ---------------------------------------------------------------------------


class TestRequiresHistory:
    def test_propose_mode(self):
        lm = LearningMachine(
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.PROPOSE,
                knowledge=_mock_knowledge(),
            ),
        )
        assert lm.requires_history is True

    def test_agentic_mode(self):
        lm = LearningMachine(
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                knowledge=_mock_knowledge(),
            ),
        )
        assert lm.requires_history is False

    def test_always_mode(self):
        lm = LearningMachine(
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.ALWAYS,
                knowledge=_mock_knowledge(),
            ),
        )
        assert lm.requires_history is False

    def test_no_learned_knowledge(self):
        lm = LearningMachine()
        assert lm.requires_history is False


# ---------------------------------------------------------------------------
# set_learning_machine auto-enables add_history_to_context
# ---------------------------------------------------------------------------


class TestSetLearningMachineHistory:
    def _make_agent(self, mode: LearningMode, add_history: bool = False) -> Agent:
        agent = Agent(
            db=MagicMock(),
            learning=LearningMachine(
                learned_knowledge=LearnedKnowledgeConfig(
                    mode=mode,
                    knowledge=_mock_knowledge(),
                ),
            ),
            add_history_to_context=add_history,
        )
        return agent

    def test_propose_enables_history(self):
        agent = self._make_agent(LearningMode.PROPOSE)
        assert agent.add_history_to_context is False

        set_learning_machine(agent)
        assert agent.add_history_to_context is True

    def test_propose_preserves_existing_history_true(self):
        agent = self._make_agent(LearningMode.PROPOSE, add_history=True)
        set_learning_machine(agent)
        assert agent.add_history_to_context is True

    def test_agentic_does_not_enable_history(self):
        agent = self._make_agent(LearningMode.AGENTIC)
        set_learning_machine(agent)
        assert agent.add_history_to_context is False
