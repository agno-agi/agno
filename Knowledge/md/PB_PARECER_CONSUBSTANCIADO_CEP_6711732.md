
## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

## PARECER CONSUBSTANCIADO DO CEP

## DADOS DO PROJETO DE PESQUISA
Pesquisador:
Título da Pesquisa: Identificação de subfenótipos da COVID longa para otimização de resultados em pacientes
Instituição Proponente:
Versão:
CAAE:
Valdilea Gonçalves Veloso dos Santos
INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS -
2
77857024.0.0000.5262
área Temática:
Pesquisas com coordenação e/ou patrocínio originados fora do Brasil, excetuadas aquelas com copatrocínio do Governo Brasileiro;
Western University
Patrocinador Principal:

## DADOS DO PARECER
Número do Parecer:
6.711.732

## Apresentação do Projeto:
Os tópicos Apresentação do projeto, Objetivo da Pesquisa e Avaliação dos Riscos e Benefícios estão de acordo com o documento ¿PB\_INFORMAÇÕES\_BáSICAS\_DO\_PROJETO\_2264167.pdf¿, versão 2, postado na Plataforma Brasil em 15/03/2024:

## Introdução:
COVID longa refere-se à condição em que as pessoas apresentam sintomas e complicações persistentes após a recuperação da fase aguda da COVID-19. Os dados publicados sugerem que a COVID longa contém diversos subfenótipos e que a prevalência e o impacto da COVID longa podem diferir conforme o país. A melhor compreensão dos subfenótipos e fatores complicadores da COVID longa ajudará a mobilizar e priorizar os recursos dos pacientes, estratificá-los para estudos de pesquisa e otimizar possíveis intervenções.

## Hipótese:
COVID longa contem diversos subfenotipos espera se obter uma melhor compreensão dos subfenotipos e complicadores do COVID longa.
Metodologia proposta:

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuação do Parecer: 6.711.732
- A) Aprendizado de máquina: subfenotipagem clínica: Os dados dos pacientes com COVID longa serão obtidos em um mínimo de 5 locais, incluindo Londres, Montreal, San Diego, Lusaka e Rio de Janeiro. Os conjuntos  de  dados  de  pacientes  conterão  até  540  pontos  clínicos  que  exigem  etapas  de  préprocessamento de dados, como tratamento de valores ausentes, normalização e detecção de valores discrepantes.  Esse  processo  inicial  será  realizado  utilizando  o  Python  (v  3.9.7)  e  bibliotecas  de processamento de dados relevantes. Após o pré-processamento, conduziremos 3 abordagens de AM: (1) Análise Exploratória de Dados (AED) para compreender a distribuição, correlação e natureza dos 540 pontos de dados clínicos. Técnicas de visualização como t-SNE e matrizes de correlação serão utilizadas para capturar padrões e anomalias. O objetivo da AED é verificar a qualidade e características dos dados, facilitando a seleção de modelos de AM adequados;
- (2) Classificadores de AM para construir um classificador Random Forest, um método de conjunto poderoso para classificar a probabilidade dos pacientes de terem um subfenótipo específico de COVID longa com base em seus dados clínicos. A regressão logística será usada para gerar curvas ROC, a partir das quais calcularemos as pontuações AUC, precisão, recuperação e F1, para fornecer uma compreensão abrangente do desempenho do classificador; e
- (3) Importância do recurso em Random Forests para obter insights mais profundos sobre variáveis significativas relacionadas ao status do subfenótipo de COVID longa. Os principais recursos, classificados por suas pontuações de importância, serão considerados preditores potencialmente significativos e serão submetidos a análises adicionais.
- B) Reconhecimento de Entidades Nomeadas e Pequeno/Grande Modelo de Linguagem: abordagem analítica acima identificará subfenótipos e características de COVID longa e será complementada com duas abordagens adicionais usando os relatórios clínicos descritivos:
- (1) REN [um processo baseado em regras] e (2) SLLMs [desenvolvimento de pré-treinamento e instruções]. Além disso, há uma parceria com a Birlasoft/Google AI sendo explorada para duas abordagens adicionais:
- (1) Zero ou Few-Shot Learning com Med-PaLM 2 LLM para extrair recursos relevantes de nosso conjunto de dados que podem permitir que o modelo entenda e classifique dados com exemplos anteriores mínimos, tornando-os inestimáveis para explorar recursos que podem ser negligenciados por métodos convencionais;
e

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuação do Parecer: 6.711.732
- (2) O modelo de LLM, Med-PaLM 2, será contratado como ¿colaborador de pesquisa¿, auxiliando na análise de resultados derivados de métodos tradicionais de AM.
- C) Análises Bioinformáticas: nosso pipeline é projetado especificamente para a análise de dados proteômicos/NGS e metabolômicos, e é capaz de:
- i) identificar com precisão os tipos de células e sua composição em tecidos complexos, inferindo estágios de desenvolvimento celular e trajetórias pseudotemporais;
- ii) identificar vias específicas do tipo celular e mecanismos putativos numa comparação fenotípica; e
- iii) identificar doenças associadas a determinados padrões de sinalização e, finalmente, associar fármacos a esses padrões. Nosso pipeline será capaz de realizar a deconvolução de dados de expressão em massa para identificar a composição do tipo de célula de cada amostra em massa. A integração do nosso pipeline com dados em massa permite a criação de conhecimento em nível de sistema que contém características essenciais para o desenvolvimento celular e a exploração de informações valiosas disponíveis a partir de tipos específicos de células e conjuntos de dados unicelulares.
- D) Redirecionamento de fármacos: Uma característica importante do nosso pipeline é a pesquisa de fármacos, incluindo o redirecionamento de fármacos. O conceito de redirecionamento de fármacos baseiase no fato de que muitos fármacos têm múltiplos alvos moleculares e mecanismos de ação, e seus efeitos podem se estender além do uso inicial pretendido.

## Critérios de Inclusão:
Critérios de inclusão de sujeitos positivos para COVID longa (CL):
¿ COVID-19 anterior (infectada por SARS-CoV-2, positiva em PCR nasofaríngeo ou teste de antígeno) com COVID longa.
Critérios de inclusão de sujeitos com longo período de COVID negativa (CL-):
- ¿ COVID-19 anterior (infetado com SARS-CoV-2, positivo na PCR nasofaríngea ou no teste de antígeno) sem COVID-19 longo (definido como um sujeito que confirmou a infecção por SARS-CoV-2 com resolução completa dos sintomas e que não cumpre a definição da OMS de sintomas persistentes ou novos sintomas 3 meses após a infecção.

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ
Continuação do Parecer: 6.711.732
Sujeitos do grupo controle saudável (CS):
- ¿  Indivíduos  sem  um  diagnóstico  bioquímico  de  SARS-CoV-2  e  sem  doença,  doença  aguda  ou medicamentos prescritos. Poderá haver a possibilidade de estes doentes terem tido SARS-CoV-2 mas não terem efetuado o teste. Também serão incluídos indivíduos de HC com biobanco recolhidos antes do aparecimento local do SARS-CoV-2 (plasma citrato, armazenado a -80oC).

## Critérios de Exclusão:
- ¿ Participantes que não atendam aos critérios descritos acima;
- ¿ Participantes que não conseguem fornecer seu consentimento informado.
Metodologia de Análise de Dados:
Métodos estatísticos:
- ¿ Variáveis demográficas serão comparadas entre sujeitos anteriormente infectados com SARS COV 2 e sofrendo COVID longa (CL+), sujeitos anteriormente infectados com SARS-COV-2 sem COVID longa (CL¿) e grupo controle saudável (CS) usando estatísticas convencionais.
- ¿  As  variáveis  clínicas  e  autorrelatadas  serão  analisadas  com  aprendizado  de  maquina  (AM), reconhecimento de entidades nomeadas (REN) e pequeno/grande modelo de linguagem (SLLMs). ¿ Os dados proteômicos/metabolômicos serão analisados com aprendizado de máquina (AM) / análises bioinformáticas (AB).
Desfecho Primário:
O endpoint principal será a identificação dos subfenótipos COVID longa.
Tamanho da Amostra no Brasil: 200
Tamanho da Amostra neste Centro: 200
Grupo único: coleta de amostras e questionário.
O Estudo é Multicêntrico no Brasil? Não.

## Objetivo da Pesquisa:
Objetivo Primário:

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuação do Parecer: 6.711.732
O principal objetivo deste estudo será identificar subfenótipos da COVID longa por meio de análises de dados clínicos do paciente, juntamente com suas proteínas plasmáticas e metabólitos.

## Objetivos Secundários:
- 1. Para determinar diferenças geográficas em subfenótipos.
- 2. Determinar novos alvos terapêuticos para reaproveitamento e/ou desenvolvimento de fármacos.

## Avaliação dos Riscos e Benefícios:
Riscos:
Os riscos antecipados para os participantes que concordam em fazer parte deste estudo são limitados. Reconhecemos que o medo de retirar sangue pode ser uma preocupação, especialmente para aqueles que têm transtorno de ansiedade. Nossa equipe estará atenta para atender qualquer necessidade que você possa vir a ter em relação a essa coleta de sangue.
Riscos da coleta de sangue incluem: dor no local da entrada da agulha, manchas roxas ou vermelhidão da pele e para algumas pessoas sensação de desmaio. Também poderá ocorrer uma eventual quebra de sigilo e da confidencialidade dos dados. Para minimizar a possibilidade de risco de quebra de sigilo e assegurar a integridade e confidencialidade dos dados adotaremos as seguintes medidas: removeremos qualquer identificação pessoal que possa vincular as informações a um participante específico; armazenamento seguro e restrição de acesso aos dados, onde somente a equipe do estudo, devidamente treinada e autorizada terá acesso. Os dados coletados serão utilizados exclusivamente para os propósitos delineados no protocolo de pesquisa, não sendo compartilhados ou utilizados para outros fins sem o consentimento explícito dos participantes.

## Benefícios:
Ao participar deste estudo, é importante destacar que o participante pode não receber benefícios diretos. No entanto, as informações coletadas durante este estudo têm o potencial de contribuir para o desenvolvimento de  tratamentos  aprimorados  para  a  COVID  longa  no  futuro.  Os  dados  dos  participantes  podem desempenhar um papel fundamental no avanço do entendimento e abordagem terapêutica dessa condição prolongada.

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ
Continuação do Parecer: 6.711.732

## Comentários e Considerações sobre a Pesquisa:
Este estudo pretende ¿identificar subfenótipos da COVID longa por meio de análises de dados clínicos do paciente, juntamente com suas proteínas plasmáticas e metabólitos¿. A metodologia de análise de dados é constituída de variáveis demográficas que serão comparadas entre participantes anteriormente infectados com SARS-COV-2 e sofrendo COVID longa (CL+), participantes anteriormente infectados com SARS-COV2 sem COVID longa (CL¿) e grupo controle saudável (CS) usando estatísticas convencionais.
Trata-se de respostas às pendências contidas no Parecer Consubstanciado n. 6.693.102, emitido em 08/03/2024.
Vide tópico ¿Conclusões ou Pendências e Lista de Inadequações¿.

## Considerações sobre os Termos de apresentação obrigatória:
Foram anexados à Plataforma Brasil os seguintes documentos:
- 1. CL\_carta\_resposta\_parecer\_6693102 (formatos em .docx e .pdf);
- 2. TCLE\_CL\_negativo\_14mar24 (marcado e limpo);
- 3. TCLE\_CL\_positivo\_14mar24 (marcado e limpo);
- 4. TCLE\_controle\_14mar24 (marcado e limpo);
- 5. PB\_INFORMAÇÕES\_BáSICAS\_DO\_PROJETO\_2264167.pdf.
Vide tópico ¿Conclusões ou Pendências e Lista de Inadequações¿.

## Recomendações:
Vide tópico ¿Conclusões ou Pendências e Lista de Inadequações¿.

## Conclusões ou Pendências e Lista de Inadequações:
No Parecer Consubstanciado n. 6.693.102 as seguintes pendências foram assinaladas:
- 1) Sobre eventuais riscos aos participantes:
No projeto original e nos TCLE apresentados, o tópico referente aos potenciais riscos aos participantes não contempla uma eventual quebra de sigilo e da confidencialidade dos dados.

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuação do Parecer: 6.711.732
PENDêNCIA: Incluir entre os potenciais riscos aos participantes a possibilidade de quebra de sigilo e da confidencialidade dos dados e medidas para prevenir;
RESPOSTA: No TCLE foi acrescentado ao item riscos o seguinte texto em destaque abaixo:

## Riscos e restrições
Os riscos antecipados para os participantes que concordam em fazer parte deste estudo são limitados. Reconhecemos que o medo de retirar sangue pode ser uma preocupação, especialmente para aqueles que têm transtorno de ansiedade. Nossa equipe estará atenta para atender qualquer necessidade que você possa vir a ter em relação a essa coleta de sangue. Riscos da coleta de sangue incluem: dor no local da entrada da agulha, manchas roxas ou vermelhidão da pele e para algumas pessoas sensação de desmaio. Também poderá ocorrer uma eventual quebra de sigilo e da confidencialidade dos dados. Para minimizar a possibilidade de risco de quebra de sigilo e assegurar a integridade e confidencialidade dos dados adotaremos as seguintes medidas: removeremos qualquer identificação pessoal que possa vincular as informações a um participante específico; armazenamento seguro e restrição de acesso aos dados, onde somente a equipe do estudo, devidamente treinada e autorizada terá acesso. Os dados coletados serão utilizados  exclusivamente  para  os  propósitos  delineados  no  protocolo  de  pesquisa,  não  sendo compartilhados  ou  utilizados  para  outros  fins  sem  o  consentimento  explícito  dos  participantes.
ANáLISE E CONCLUSÃO: O texto foi incluído em todos os TCLE e no documento Informações Básicas do Projeto na Plataforma Brasil. PENDêNCIA ATENDIDA.

## 2) Sobre a coleta de dados:
Na página 2 dos TCLE, no tópico 'O que ocorrerá durante sua participação neste estudo?¿, além da verificação do histórico médico e dos sintomas relacionados à Covid-19 consta a aplicação de ¿três questionários já realizados na nossa coorte de COVID longa: um sobre depressão, outro sobre ansiedade e outro sobre sua saúde geral¿.
Também consta no projeto original (item 5. PROCEDIMENTOS DE ESTUDO, subitem 5.1GLYPH&lt;9&gt;Coleta de dados, tópico 5.1.3 Dados clínicos retrospectivos/prospectivos e coleta de bioespécimes) com o seguinte teor: ¿Os participantes preencherão os seguintes questionários durante a consulta do estudo: Lista de verificação de sintomas de COVID (no momento da infecção); Lista de verificação de

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuação do Parecer: 6.711.732
sintomas de COVID (no momento da consulta clínica/coleta de bioespécime); PHQ-9 (Ferramenta para medir a depressão); TAG-7 (Ferramenta para medir transtorno de ansiedade generalizada); e PROMIS-29 (Ferramenta para medir a intensidade da dor em 7 áreas da saúde: função física, fadiga, interferência da dor, sintomas depressivos, ansiedade, capacidade de participar em funções e atividades sociais e distúrbios do sono)¿.
ANáLISE: Na Plataforma Brasil foram anexados apenas dois questionários: PHQ-9 (depressão) e GAD-7 (ansiedade). No projeto original (item 5. PROCEDIMENTOS DE ESTUDO, subitem 5.1 Coleta de dados, tópico 5.1.1 Agenda de eventos) está relatado que a ferramenta PROMIS-29 será aplicada apenas em San Diego (EUA) na coleta de dados clínicos retrospectivos, mas em todas as 5 cidades na coleta prospectiva dos dados.
PENDêNCIA: Esclarecer a ausência da ferramenta PROMIS-29 entre os arquivos obrigatórios anexados, ou qual questionário será utilizado para obtenção de dados ¿sobre sua saúde geral¿, conforme descrito nos TCLE.
RESPOSTA: Os questionários já estavam contidos no item 8 - apêndice do protocolo. Feito com detalhamento abaixo:
Página do protocoloGLYPH&lt;9&gt;Questionário
19GLYPH&lt;9&gt;GLYPH&lt;9&gt;GLYPH&lt;9&gt;GAD 7
22GLYPH&lt;9&gt;GLYPH&lt;9&gt;GLYPH&lt;9&gt;PROMIS 29
29GLYPH&lt;9&gt;GLYPH&lt;9&gt;GLYPH&lt;9&gt;PHQ 9
Porém para melhor visualização foi colocado também como arquivo anexo.

## CONCLUSÃO: PENDêNCIA ATENDIDA.
Este relatório pode ser aprovado ad referendum.
Este projeto será encaminhado à Conep (área Temática) após aprovação.

## Considerações Finais a critério do CEP:
O projeto será encaminhado à Conep (área Temática).

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuação do Parecer: 6.711.732

## O presente projeto, seguiu nesta data para análise da CONEP e só tem o seu início autorizado após a aprovação pela mesma.

## Este parecer foi elaborado baseado nos documentos abaixo relacionados:
| Tipo Documento                                                     | Arquivo                                                        | Postagem            | Autor                           | Situação   |
|--------------------------------------------------------------------|----------------------------------------------------------------|---------------------|---------------------------------|------------|
| Informações Básicas do Projeto                                     | PB_INFORMAÇÕES_BáSICAS_DO_P ROJETO_2264167.pdf                 | 15/03/2024 09:06:41 |                                 | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de Ausência          | TCLE_controle_14mar24_marcado.docx                             | 15/03/2024 09:06:08 | Tânia Krstic                    | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de Ausência          | TCLE_controle_14mar24_limpo.pdf                                | 15/03/2024 09:01:02 | Tânia Krstic                    | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de Ausência          | TCLE_CL_positivo_14mar24_marcado.d ocx                         | 15/03/2024 09:00:51 | Tânia Krstic                    | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de Ausência          | TCLE_CL_positivo_14mar24_limpo.pdf                             | 15/03/2024 09:00:39 | Tânia Krstic                    | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de                   | TCLE_CL_negativo_14mar24_marcado. docx                         | 15/03/2024 09:00:28 | Tânia Krstic                    | Aceito     |
| Ausência TCLE / Termos de Assentimento / Justificativa de Ausência | TCLE_CL_negativo_14mar24_limpo.pdf                             | 15/03/2024 09:00:17 | Tânia Krstic                    | Aceito     |
| Outros                                                             | CL_carta_resposta_parecer_6693102_a ssinado.pdf                | 15/03/2024 09:00:01 | Tânia Krstic                    | Aceito     |
| Outros                                                             | CL_carta_resposta_parecer_6693102.d ocx                        | 15/03/2024 08:59:44 | Tânia Krstic                    | Aceito     |
| Outros                                                             | BIOREPOSITORIO_29fev24_ASSINTU RA_CORRIGIDA.pdf                | 29/02/2024 19:27:09 | FABIO VINICIUS DOS REIS MARQUES | Aceito     |
| Outros                                                             | CL_carta_encaminamento_CEP_28fev2 4_Assinado.pdf               | 28/02/2024 19:45:55 | Tânia Krstic                    | Aceito     |
| Outros                                                             | CL_carta_encaminamento_CEP_28fev2 4.docx                       | 28/02/2024 19:45:33 | Tânia Krstic                    | Aceito     |
| Declaração de Manuseio Material Biológico / Biorepositório /       | Acordo_entre_instituicoes_armazename nto_amostras_assinado.pdf | 28/02/2024 19:45:21 | Tânia Krstic                    | Aceito     |

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuação do Parecer: 6.711.732
| Biobanco                                                              | Acordo_entre_instituicoes_armazename nto_amostras_assinado.pdf   | 28/02/2024 19:45:21   | Tânia Krstic   | Aceito   |
|-----------------------------------------------------------------------|------------------------------------------------------------------|-----------------------|----------------|----------|
| Declaração de Manuseio Material Biológico / Biorepositório / Biobanco | Acordo_entre_instituicoes_armazename nto_amostras.doc            | 28/02/2024 19:45:07   | Tânia Krstic   | Aceito   |
| Folha de Rosto                                                        | folhaDeRosto_assinado.pdf                                        | 28/02/2024 19:44:52   | Tânia Krstic   | Aceito   |
| TCLE / Termos de Assentimento / Justificativa de Ausência             | TCLE_controle_26fev24_final.docx                                 | 28/02/2024 19:44:39   | Tânia Krstic   | Aceito   |
| TCLE / Termos de Assentimento / Justificativa de Ausência             | TCLE_CL_positivo_26fev24_final.docx                              | 28/02/2024 15:51:47   | Tânia Krstic   | Aceito   |
| TCLE / Termos de Assentimento / Justificativa de Ausência             | TCLE_CL_negativo_26fev24_final.docx                              | 28/02/2024 15:51:35   | Tânia Krstic   | Aceito   |
| Outros                                                                | CL_aprovacao_pais_origem_port.docx                               | 19/02/2024 10:03:41   | Tânia Krstic   | Aceito   |
| Outros                                                                | CL_aprovacao_pais_origem.pdf                                     | 19/02/2024 10:03:21   | Tânia Krstic   | Aceito   |
| Outros                                                                | CL_revisao_literatura_02fev2024.pdf                              | 19/02/2024 10:02:42   | Tânia Krstic   | Aceito   |
| Outros                                                                | CL_PHQ9_questionario_Portugues.pdf                               | 19/02/2024 10:02:24   | Tânia Krstic   | Aceito   |
| Outros                                                                | CL_GAD7_questionario_Portugues.pdf                               | 19/02/2024 10:02:09   | Tânia Krstic   | Aceito   |
| Projeto Detalhado / Brochura Investigador                             | CL_Protocolo_PT_final.docx                                       | 19/02/2024 10:01:37   | Tânia Krstic   | Aceito   |
| Declaração de Manuseio Material Biológico / Biorepositório / Biobanco | CL_REGIMENTO_INTERNO_BIOREPO SITORIO_LAPCLINAIDS.pdf             | 19/02/2024 10:01:01   | Tânia Krstic   | Aceito   |
| Orçamento                                                             | CL_orcamento.xlsx                                                | 19/02/2024 09:58:18   | Tânia Krstic   | Aceito   |
| Declaração de Pesquisadores                                           | COVID_LONGA_Declaracao_finalidade _dados_Assinado.pdf            | 19/02/2024 09:56:00   | Tânia Krstic   | Aceito   |
| Declaração de Pesquisadores                                           | COVID_LONGA_Declaracao_finalidade _dados.doc                     | 19/02/2024 09:55:35   | Tânia Krstic   | Aceito   |
| Declaração de Pesquisadores                                           | COVID_LONGA_Declaracao_destino_a mostras_biologicas_Assinado.pdf | 19/02/2024 09:55:18   | Tânia Krstic   | Aceito   |

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuação do Parecer: 6.711.732
| Declaração de Pesquisadores                                           | COVID_LONGA_Declaracao_destino_a mostras_biologicas.doc                 | 19/02/2024 09:55:00   | Tânia Krstic   | Aceito   |
|-----------------------------------------------------------------------|-------------------------------------------------------------------------|-----------------------|----------------|----------|
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
Necessita Apreciação da CONEP:
Sim
RIO DE JANEIRO, 19 de Março de 2024
Maria Inês Fernandes Pimentel (Coordenador(a)) Assinado por:
