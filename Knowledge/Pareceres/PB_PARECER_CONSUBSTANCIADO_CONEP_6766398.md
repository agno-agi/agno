## COMISSÃO NACIONAL DE ÉTICA EM PESQUISA

## PARECER CONSUBSTANCIADO DA CONEP
## DADOS DO PROJETO DE PESQUISA
Pesquisador:
Título da Pesquisa: Identificação de subfenótipos da COVID longa para otimização de resultados em pacientes
Instituição Proponente:
Versão:
CAAE:
Valdilea Gonçalves Veloso dos Santos
INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS -
3
77857024.0.0000.5262
área Temática:
Pesquisas com coordenação e/ou patrocínio originados fora do Brasil, excetuadas aquelas com copatrocínio do Governo Brasileiro;
Instituição Proponente:
INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS -
Western University
Patrocinador Principal:
## DADOS DO PARECER
Número do Parecer:
6.766.398
## Apresentação do Projeto:
As informações elencadas nos campos "Apresentação do Projeto", "Objetivo da Pesquisa" e "Avaliação dos Riscos  e  Benefícios"  foram  retiradas  do  arquivo  Informações  Básicas  da  Pesquisa ( PB\_INFORMAÇÕES\_BáSICAS\_DO\_PROJETO\_2264167.pdf,  de  27/03/2024).
## INTRODUÇÃO
COVID longa refere-se à condição em que as pessoas apresentam sintomas e complicações persistentes após a recuperação da fase aguda da COVID-19. Os dados publicados sugerem que a COVID longa contém diversos subfenótipos e que a prevalência e o impacto da COVID longa podem diferir conforme o país. A melhor compreensão dos subfenótipos e fatores complicadores da COVID longa ajudará a mobilizar e priorizar os recursos dos pacientes, estratificá-los para estudos de pesquisa e otimizar possíveis intervenções.
## HIPÓTESE
Covid longa contém diversos subfenotipos espera se obter uma melhor compreensão dos subfenotipos e complicadores do covid longa.
## METODOLOGIA
## COMISSÃO NACIONAL DE ÉTICA EM PESQUISA

Continuação do Parecer: 6.766.398
- A) Aprendizado de máquina: subfenotipagem clínica: Os dados dos pacientes com COVID longa serão obtidos em um mínimo de 5 locais, incluindo Londres, Montreal, San Diego, Lusaka e Rio de Janeiro. Os conjuntos  de  dados  de  pacientes  conterão  até  540  pontos  clínicos  que  exigem  etapas  de  préprocessamento de dados, como tratamento de valores ausentes, normalização e detecção de valores discrepantes. Esse processo inicial será realizado utilizando o Python(v3.9.7)e bibliotecas de processamento de dados relevantes. Após o pré-processamento, conduziremos 3 abordagens de AM:
- (1) Análise Exploratória de Dados(AED) para compreender a distribuição, correlação e natureza dos 540 pontos de dados clínicos. Técnicas de visualização como t-SNE e matrizes de correlação serão utilizadas para capturar padrões e anomalias. O objetivo da AED é verificar a qualidade e características dos dados, facilitando a seleção de modelos de AM adequados;
- (2) classificadores de AM para construir um classificador Random Forest, um método de conjunto poderoso, para classificar a probabilidade dos pacientes de terem um subfenótipo específico de COVID longa com base em seus dados clínicos. A regressão logística será usada para gerar curvas ROC, a partir das quais calcularemos as pontuações AUC, precisão, recuperação e F1, para fornecer uma compreensão abrangente do desempenho do classificador;
- (3) Importância do recurso em Random Forests para obter insights mais profundos sobre variáveis significativas relacionadas ao status do subfenótipo de COVID longa. Os principais recursos, classificados por suas pontuações de importância, serão considerados preditores potencialmente significativos e serão submetidos a análises adicionais.
- B) Reconhecimento de Entidades Nomeadas e Pequeno/Grande Modelo de Linguagem: abordagem analítica acima identificará subfenótipos e características de COVID longa e será complementada com duas abordagens adicionais usando os relatórios clínicos descritivos:
- (1) REN [um processo baseado em regras] e
- (2) SLLMs [desenvolvimento de pré-treinamento e instruções]. Além disso, há uma parceria com a Birlasoft/Google AI sendo explorada para duas abordagens adicionais:
- (1) Zero ou Few-Shot Learning com Med-PaLM 2 LLM para extrair recursos relevantes de nosso conjunto de dados que podem permitir que o modelo entenda e classifique dados com exemplos anteriores mínimos,
tornando-os inestimáveis para explorar recursos que podem ser negligenciados por métodos convencionais;
- (2) o modelo de LLM, MedPaLM 2, será contratado como colaborador de pesquisa, auxiliando na análise de resultados derivados de métodos tradicionais de AM.
## COMISSÃO NACIONAL DE ÉTICA EM PESQUISA

Continuação do Parecer: 6.766.398
- C) Análises Bioinformáticas: nosso pipeline é projetado especificamente para a análise de dados proteômicos/NGS e metabolômicos, e é capaz de:
- i) identificar com precisão os tipos de células e sua composição em tecidos complexos, inferindo estágios de desenvolvimento celular e trajetórias pseudotemporais;
- ii) identificar vias específicas do tipo celular e mecanismos putativos numa comparação fenotípica;
- iii) identificar doenças associadas a determinados padrões de sinalização e, finalmente, associar fármacos a esses padrões. Nosso pipeline será capaz de realizar a deconvolução de dados de expressão em massa para identificar a composição do tipo de célula de cada amostra em massa. A integração do nosso pipeline com dados em massa permite a criação de conhecimento em nível de sistema que contém características essenciais para o desenvolvimento celular e a exploração de informações valiosas disponíveis a partir de tipos específicos de células e conjuntos de dados unicelulares.
- D) Redirecionamento de fármacos: Uma característica importante do nosso pipeline é a pesquisa de fármacos, incluindo o redirecionamento de fármacos. O conceito de redirecionamento de fármacos baseiase no fato de que muitos fármacos têm múltiplos alvos moleculares e mecanismos de ação, e seus efeitos podem se estender além do uso inicial pretendido.
## CRITÉRIOS DE INCLUSÃO
- - Critérios de inclusão de sujeitos positivos para COVID longa (CL) COVID-19 anterior (infectada por SARSCoV-2, positiva em PCR nasofaríngeo ou teste de antígeno) com COVID longa.
- - Critérios de inclusão de sujeitos com longo período de COVID negativa (CL-) COVID-19 anterior (infetado com SARS-CoV-2, positivo na PCR nasofaríngea ou no teste de antigénio) sem COVID-19 longo (definido como um sujeito que confirmou a infeção por SARS-CoV-2 com resolução completa dos sintomas e que não cumpre a definição da OMS de sintomas persistentes ou novos sintomas 3 meses após a infeção.
- - Sujeitos do grupo controle saudável (CS).
- -  Indivíduos  sem  um  diagnóstico  bioquímico  de  SARS-CoV-2  e  sem  doença,  doença  aguda  ou medicamentos prescritos. Poderá haver a possibilidade de estes doentes terem tido SARS-CoV-2 mas não terem efectuado o teste.
- - Também serão incluídos indivíduos de HC com biobanco recolhidos antes do aparecimento local do SARSCoV-2 (plasma citrato, armazenado a - 80oC).
Continuação do Parecer: 6.766.398
## CRITÉRIOS DE EXCLUSÃO
- - Participantes que não atendam aos critérios descritos acima.
- - Participantes que não conseguem fornecer seu consentimento informado.
## Objetivo da Pesquisa:
## OBJETIVO PRIMáRIO
O principal objetivo deste estudo será identificar subfenótipos da COVID longa por meio de análises de dados clínicos do paciente, juntamente com suas proteínas plasmáticas e metabólitos.
## OBJETIVOS SECUNDáRIOS
- 1. Para determinar diferenças geográficas em subfenótipos.
- 2. Determinar novos alvos terapêuticos para reaproveitamento e/ou desenvolvimento de fármacos.
## Avaliação dos Riscos e Benefícios:
## RISCOS
Os riscos antecipados para os participantes que concordam em fazer parte deste estudo são limitados. Reconhecemos que o medo de retirar sangue pode ser uma preocupação, especialmente para aqueles que têm transtorno de ansiedade. Nossa equipe estará atenta para atender qualquer necessidade que você possa vir a ter em relação a essa coleta de sangue.
Riscos da coleta de sangue incluem: dor no local da entrada da agulha, manchas roxas ou vermelhidão da pele e para algumas pessoas sensação de desmaio. Também poderá ocorrer uma eventual quebra de sigilo e da confidencialidade dos dados. Para minimizar a possibilidade de risco de quebra de sigilo e assegurar a integridade e confidencialidade dos dados adotaremos as seguintes medidas: removeremos qualquer identificação pessoal que possa vincular as informações a um participante específico; armazenamento seguro e restrição de acesso aos dados, onde somente a equipe do estudo, devidamente treinada e autorizada terá acesso. Os dados coletados serão utilizados exclusivamente para os propôs
## BENEFÍCIOS
Ao participar deste estudo, é importante destacar que você pode não receber benefícios
## COMISSÃO NACIONAL DE ÉTICA EM PESQUISA

## COMISSÃO NACIONAL DE ÉTICA EM PESQUISA

Continuação do Parecer: 6.766.398
diretos. No entanto, as informações coletadas durante este estudo têm o potencial de contribuir para o desenvolvimento de tratamentos aprimorados para a COVID longa no futuro. Seus dados podem desempenhar um papel fundamental no avanço do entendimento e abordagem terapêutica dessa condição prolongada. Sua participação é importante e pode impactar positivamente a saúde de outras pessoas no futuro. Se tiver alguma dúvida sobre o propósito ou benefícios potenciais deste estudo, a equipe do estudo está disponível para fornecer mais informações.
## Comentários e Considerações sobre a Pesquisa:
COVID longa refere-se à condição em que as pessoas apresentam sintomas e complicações persistentes após a recuperação da fase aguda da COVID-19. Os dados publicados sugerem que a COVID longa contém diversos subfenótipos e que a prevalência e o impacto da COVID longa podem diferir conforme o país. A melhor compreensão dos subfenótipos e fatores complicadores da COVID longa ajudará a mobilizar e priorizar os recursos dos pacientes, estratificá-los para estudos de pesquisa e otimizar possíveis intervenções. Os dados clínicos retrospectivos serão coletados ao longo de 3 meses nos locais de estudo
Este é um estudo de coorte com três braços de estudo:
- - Análises de dados clínicos retrospectivos com AM/LLMs.
- - Análises de bioespécimes coletados retrospectivamente/prospectivamente com AM/AB.
- - Análises de dados proteômicos/metabolômicos para descoberta de fármacos com métodos AB/ortogonais.
Patrocinador: Western University
Financiador: Schmidt Initiative for Long COVID (SILC)
País de Origem: Estados Unidos da América
Aprovação ética do país de origem: finalizada
Haverá armazenamento de material biológico em Biorrepositório: As amostras são enviadas à Translational Research Center (TRC) do Victoria Hospital em Londres, Ontário, Canadá que é responsável pelo armazenamento das amostras do estudo.
## COMISSÃO NACIONAL DE ÉTICA EM PESQUISA
Continuação do Parecer: 6.766.398
## Considerações sobre os Termos de apresentação obrigatória:
Vide campo "Conclusões ou Pendências e Lista de Inadequações".
## Conclusões ou Pendências e Lista de Inadequações:
Não foram identificados óbices éticos neste protocolo.
## Considerações Finais a critério da CONEP:
Diante do exposto, a Comissão Nacional de Ética em Pesquisa - Conep, de acordo com as atribuições definidas na Resolução CNS n' 466 de 2012 e na Norma Operacional n' 001 de 2013 do CNS, manifesta-se pela aprovação do projeto de pesquisa proposto.
Situação: Protocolo aprovado.
## Este parecer foi elaborado baseado nos documentos abaixo relacionados:
| Tipo Documento                                            | Arquivo                                        | Postagem            | Autor        | Situação   |
|-----------------------------------------------------------|------------------------------------------------|---------------------|--------------|------------|
| Informações Básicas do Projeto                            | PB_INFORMAÇÕES_BáSICAS_DO_P ROJETO_2264167.pdf | 27/03/2024 18:18:14 |              | Aceito     |
| Folha de Rosto                                            | FR_assinada_27mar24.pdf                        | 27/03/2024 18:00:54 | Tânia Krstic | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de Ausência | TCLE_controle_14mar24_marcado.docx             | 15/03/2024 09:06:08 | Tânia Krstic | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de Ausência | TCLE_controle_14mar24_limpo.pdf                | 15/03/2024 09:01:02 | Tânia Krstic | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de Ausência | TCLE_CL_positivo_14mar24_marcado.d ocx         | 15/03/2024 09:00:51 | Tânia Krstic | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de Ausência | TCLE_CL_positivo_14mar24_limpo.pdf             | 15/03/2024 09:00:39 | Tânia Krstic | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de Ausência | TCLE_CL_negativo_14mar24_marcado. docx         | 15/03/2024 09:00:28 | Tânia Krstic | Aceito     |
## COMISSÃO NACIONAL DE ÉTICA EM PESQUISA

Continuação do Parecer: 6.766.398
| TCLE / Termos de Assentimento / Justificativa de Ausência             | TCLE_CL_negativo_14mar24_limpo.pdf                             | 15/03/2024 09:00:17   | Tânia Krstic                    | Aceito   |
|-----------------------------------------------------------------------|----------------------------------------------------------------|-----------------------|---------------------------------|----------|
| Outros                                                                | CL_carta_resposta_parecer_6693102_a ssinado.pdf                | 15/03/2024 09:00:01   | Tânia Krstic                    | Aceito   |
| Outros                                                                | CL_carta_resposta_parecer_6693102.d ocx                        | 15/03/2024 08:59:44   | Tânia Krstic                    | Aceito   |
| Outros                                                                | BIOREPOSITORIO_29fev24_ASSINTU RA_CORRIGIDA.pdf                | 29/02/2024 19:27:09   | FABIO VINICIUS DOS REIS MARQUES | Aceito   |
| Outros                                                                | CL_carta_encaminamento_CEP_28fev2 4_Assinado.pdf               | 28/02/2024 19:45:55   | Tânia Krstic                    | Aceito   |
| Outros                                                                | CL_carta_encaminamento_CEP_28fev2 4.docx                       | 28/02/2024 19:45:33   | Tânia Krstic                    | Aceito   |
| Declaração de Manuseio Material Biológico / Biorepositório / Biobanco | Acordo_entre_instituicoes_armazename nto_amostras_assinado.pdf | 28/02/2024 19:45:21   | Tânia Krstic                    | Aceito   |
| Declaração de Manuseio Material Biológico / Biorepositório / Biobanco | Acordo_entre_instituicoes_armazename nto_amostras.doc          | 28/02/2024 19:45:07   | Tânia Krstic                    | Aceito   |
| TCLE / Termos de Assentimento / Justificativa de Ausência             | TCLE_controle_26fev24_final.docx                               | 28/02/2024 19:44:39   | Tânia Krstic                    | Aceito   |
| TCLE / Termos de Assentimento / Justificativa de                      | TCLE_CL_positivo_26fev24_final.docx                            | 28/02/2024 15:51:47   | Tânia Krstic                    | Aceito   |
| Ausência TCLE / Termos de Assentimento / Justificativa de Ausência    | TCLE_CL_negativo_26fev24_final.docx                            | 28/02/2024 15:51:35   | Tânia Krstic                    | Aceito   |
| Outros                                                                | CL_aprovacao_pais_origem_port.docx                             | 19/02/2024 10:03:41   | Tânia Krstic                    | Aceito   |
| Outros                                                                | CL_aprovacao_pais_origem.pdf                                   | 19/02/2024 10:03:21   | Tânia Krstic                    | Aceito   |
| Outros                                                                | CL_revisao_literatura_02fev2024.pdf                            | 19/02/2024 10:02:42   | Tânia Krstic                    | Aceito   |
| Outros                                                                | CL_PHQ9_questionario_Portugues.pdf                             | 19/02/2024 10:02:24   | Tânia Krstic                    | Aceito   |
| Outros                                                                | CL_GAD7_questionario_Portugues.pdf                             | 19/02/2024 10:02:09   | Tânia Krstic                    | Aceito   |
## COMISSÃO NACIONAL DE ÉTICA EM PESQUISA

Continuação do Parecer: 6.766.398
| Projeto Detalhado / Brochura Investigador                             | CL_Protocolo_PT_final.docx                                              | 19/02/2024 10:01:37   | Tânia Krstic   | Aceito   |
|-----------------------------------------------------------------------|-------------------------------------------------------------------------|-----------------------|----------------|----------|
| Declaração de Manuseio Material Biológico / Biorepositório / Biobanco | CL_REGIMENTO_INTERNO_BIOREPO SITORIO_LAPCLINAIDS.pdf                    | 19/02/2024 10:01:01   | Tânia Krstic   | Aceito   |
| Orçamento                                                             | CL_orcamento.xlsx                                                       | 19/02/2024 09:58:18   | Tânia Krstic   | Aceito   |
| Declaração de Pesquisadores                                           | COVID_LONGA_Declaracao_finalidade _dados_Assinado.pdf                   | 19/02/2024 09:56:00   | Tânia Krstic   | Aceito   |
| Declaração de Pesquisadores                                           | COVID_LONGA_Declaracao_finalidade _dados.doc                            | 19/02/2024 09:55:35   | Tânia Krstic   | Aceito   |
| Declaração de Pesquisadores                                           | COVID_LONGA_Declaracao_destino_a mostras_biologicas_Assinado.pdf        | 19/02/2024 09:55:18   | Tânia Krstic   | Aceito   |
| Declaração de Pesquisadores                                           | COVID_LONGA_Declaracao_destino_a mostras_biologicas.doc                 | 19/02/2024 09:55:00   | Tânia Krstic   | Aceito   |
| Declaração de Pesquisadores                                           | COVID_LONGA_Declaracao_desenho_ estudo_Assinado.pdf                     | 19/02/2024 09:54:36   | Tânia Krstic   | Aceito   |
| Declaração de Pesquisadores                                           | COVID_LONGA_Declaracao_desenho_ estudo.doc                              | 19/02/2024 09:54:14   | Tânia Krstic   | Aceito   |
| Declaração de Pesquisadores                                           | COVID_LONGA_Declaracao_cumprime nto_resolucoes_Assinado.pdf             | 19/02/2024 09:53:56   | Tânia Krstic   | Aceito   |
| Declaração de Pesquisadores                                           | COVID_LONGA_Declaracao_cumprime nto_resolucoes.doc                      | 19/02/2024 09:53:19   | Tânia Krstic   | Aceito   |
| Declaração de Manuseio Material Biológico / Biorepositório / Biobanco | COVID_LONGA_Regulamento_Armaze na_Amostras_Testes_Futuros_Assinado .pdf | 19/02/2024 09:53:06   | Tânia Krstic   | Aceito   |
| Declaração de Manuseio Material Biológico / Biorepositório / Biobanco | COVID_LONGA_Regulamento_Armaze na_Amostras_Testes_Futuros.doc           | 19/02/2024 09:52:31   | Tânia Krstic   | Aceito   |
| Declaração de Instituição e Infraestrutura                            | COVID_LONGA_Declaracao_de_Infraes trutura_e_Instalacoes_Assinado.pdf    | 19/02/2024 09:52:00   | Tânia Krstic   | Aceito   |
| Declaração de Instituição e Infraestrutura                            | COVID_LONGA_Declaracao_de_Infraes trutura_e_Instalacoes.doc             | 19/02/2024 09:51:33   | Tânia Krstic   | Aceito   |
## Situação do Parecer:
Aprovado
Continuação do Parecer: 6.766.398
## COMISSÃO NACIONAL DE ÉTICA EM PESQUISA
BRASILIA, 22 de Abril de 2024
Laís Alves de Souza Bonilha (Coordenador(a)) Assinado por:
