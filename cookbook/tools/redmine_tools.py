from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.redmine import RedmineTools

agent = Agent(model= Gemini("gemini-2.0-flash-exp"), tools=[RedmineTools()])
# agent.print_response("Find all issues in project PrimeiroTeste", markdown=True)
# agent.print_response("Add comment 'viewed' to issue 1", markdown=True)
# agent.print_response("Adicione comentário 'aprovado' a tarefa 1", markdown=True)
# agent.print_response("Get details from issue 1", markdown=True)
# agent.print_response("Find all issues where subject contains 'defeitos'", markdown=True)
# agent.print_response("Find all issues where subject contains 'inteligente'", markdown=True)

# agent.print_response("Encontre todas as tarefas cujo assunto contenha 'inteligente' e mostre seus dados.", markdown=True)

# agent.print_response("Mostre os detalhes da tarefa com id 3", markdown=True)

# agent.print_response("Adicione o comentário 'revisado' na tarefa com id 3", markdown=True)

agent.print_response("Crie nova tarefa no projeto 'primeiro-teste' com o sumário 'Tá quase pronto', descrição 'Que marravilhaaaaaa', do tipo 'Funcionalidade'", markdown=True)
