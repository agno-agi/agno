## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

<!-- image -->

## PARECER CONSUBSTANCIADO DO CEP

## DADOS DO PROJETO DE PESQUISA

Pesquisador:

Título da Pesquisa: Identificaçªo de subfenótipos da COVID longa para otimizaçªo de resultados em pacientes

Instituiçªo Proponente: INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI/FIOCRUZ Western University Patrocinador Principal:

Versªo:

CAAE:

Valdilea Gonçalves Veloso dos Santos

1

77857024.0.0000.5262

`rea TemÆtica: Pesquisas com coordenaçªo e/ou patrocínio originados fora do Brasil, excetuadas aquelas

com copatrocínio do Governo Brasileiro;

## DADOS DO PARECER

Nœmero do Parecer:

6.693.102

## Apresentaçªo do Projeto:

Os tópicos Apresentaçªo do projeto, Objetivo da Pesquisa e Avaliaçªo dos Riscos e Benefícios estªo de acordo  com  os  documentos  'PB\_INFORMA˙ÕES\_B`SICAS\_DO\_PROJETO\_2264167.pdf'  e 'CL\_Protocolo\_PT\_final.docx',  postados  na  Plataforma  Brasil  em  28/02/2024  e  19/02/2024, respectivamente:

## Introduçªo:

COVID longa refere-se à condiçªo em que as pessoas apresentam sintomas e complicaçıes persistentes após a recuperaçªo da fase aguda da COVID-19. Os dados publicados sugerem que a COVID longa contØm diversos subfenótipos e que a prevalŒncia e o impacto da COVID longa podem diferir conforme o país. A melhor compreensªo dos subfenótipos e fatores complicadores da COVID longa ajudarÆ a mobilizar e priorizar os recursos dos pacientes, estratificÆ-los para estudos de pesquisa e otimizar possíveis intervençıes.

## Hipótese:

COVID longa contem diversos subfenotipos espera se obter uma melhor compreensªo dos subfenotipos e complicadores do COVID longa.

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço:

Bairro:

CEP:

Telefone:

Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Manguinhos

UF: RJ

Município:

RIO DE JANEIRO

Continuaçªo do Parecer: 6.693.102

## Metodologia proposta:

A) Aprendizado de mÆquina (AM): subfenotipagem clínica: Os dados dos pacientes com COVID longa serªo obtidos em um mínimo de 5 locais, incluindo Londres, Montreal, San Diego, Lusaka e Rio de Janeiro. Os conjuntos  de  dados  de  pacientes  conterªo  atØ  540  pontos  clínicos  que  exigem  etapas  de  prØprocessamento de dados, como tratamento de valores ausentes, normalizaçªo e detecçªo de valores discrepantes.  Esse  processo  inicial  serÆ  realizado  utilizando  o  Python  (v  3.9.7)  e  bibliotecas  de processamento de dados relevantes. Após o prØ-processamento, conduziremos 3 abordagens de AM: (1) AnÆlise Exploratória de Dados (AED) para compreender a distribuiçªo, correlaçªo e natureza dos 540 pontos de dados clínicos. TØcnicas de visualizaçªo como t-SNE e matrizes de correlaçªo serªo utilizadas

- para capturar padrıes e anomalias. O objetivo da AED Ø verificar a qualidade e características dos dados, facilitando a seleçªo de modelos de AM adequados;
- (2) Classificadores de AM para construir um classificador Random Forest, um mØtodo de conjunto poderoso para classificar a probabilidade dos pacientes de terem um subfenótipo específico de COVID longa com base em seus dados clínicos. A regressªo logística serÆ usada para gerar curvas ROC, a partir das quais calcularemos as pontuaçıes AUC, precisªo, recuperaçªo e F1, para fornecer uma compreensªo abrangente do desempenho do classificador; e
- (3) Importância do recurso em Random Forests para obter insights mais profundos sobre variÆveis significativas relacionadas ao status do subfenótipo de COVID longa. Os principais recursos, classificados por suas pontuaçıes de importância, serªo considerados preditores potencialmente significativos e serªo submetidos a anÆlises adicionais.
- B) Reconhecimento de Entidades Nomeadas e Pequeno/Grande Modelo de Linguagem: abordagem analítica acima identificarÆ subfenótipos e características de COVID longa e serÆ complementada com duas abordagens adicionais usando os relatórios clínicos descritivos:
- (1) REN [um processo baseado em regras] e (2) SLLMs [desenvolvimento de prØ-treinamento e instruçıes]. AlØm disso, hÆ uma parceria com a Birlasoft/Google AI sendo explorada para duas abordagens adicionais:
- (1) Zero ou Few-Shot Learning com Med-PaLM 2 LLM para extrair recursos relevantes de nosso conjunto de dados que podem permitir que o modelo entenda e classifique dados com exemplos anteriores mínimos, tornando-os inestimÆveis para explorar recursos que podem ser negligenciados por mØtodos convencionais;

e

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço:

Bairro:

CEP:

Telefone:

Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Manguinhos

UF: RJ

Município:

RIO DE JANEIRO

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

<!-- image -->

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

<!-- image -->

Continuaçªo do Parecer: 6.693.102

- (2) O modelo de LLM, Med-PaLM 2, serÆ contratado como 'colaborador de pesquisa', auxiliando na anÆlise de resultados derivados de mØtodos tradicionais de AM.
- C) AnÆlises BioinformÆticas: nosso pipeline Ø projetado especificamente para a anÆlise de dados proteômicos/NGS e metabolômicos, e Ø capaz de:
- i) identificar com precisªo os tipos de cØlulas e sua composiçªo em tecidos complexos, inferindo estÆgios de desenvolvimento celular e trajetórias pseudotemporais;
- ii) identificar vias específicas do tipo celular e mecanismos putativos numa comparaçªo fenotípica; e
- iii) identificar doenças associadas a determinados padrıes de sinalizaçªo e, finalmente, associar fÆrmacos a esses padrıes. Nosso pipeline serÆ capaz de realizar a deconvoluçªo de dados de expressªo em massa para identificar a composiçªo do tipo de cØlula de cada amostra em massa. A integraçªo do nosso pipeline com dados em massa permite a criaçªo de conhecimento em nível de sistema que contØm características essenciais para o desenvolvimento celular e a exploraçªo de informaçıes valiosas disponíveis a partir de tipos específicos de cØlulas e conjuntos de dados unicelulares.
- D) Redirecionamento de fÆrmacos: Uma característica importante do nosso pipeline Ø a pesquisa de fÆrmacos, incluindo o redirecionamento de fÆrmacos. O conceito de redirecionamento de fÆrmacos baseiase no fato de que muitos fÆrmacos tŒm mœltiplos alvos moleculares e mecanismos de açªo, e seus efeitos podem se estender alØm do uso inicial pretendido.

CritØrios de Inclusªo:

CritØrios de inclusªo de sujeitos positivos para COVID longa (CL):

- · COVID-19 anterior (infectada por SARS-CoV-2, positiva em PCR nasofaríngeo ou teste de antígeno) com COVID longa.

CritØrios de inclusªo de sujeitos com longo período de COVID negativa (CL-):

- · COVID-19 anterior (infetado com SARS-CoV-2, positivo na PCR nasofaríngea ou no teste de antígeno) sem COVID-19 longo (definido como um sujeito que confirmou a infecçªo por SARS-CoV-2 com resoluçªo completa dos sintomas e que nªo cumpre a definiçªo da OMS de sintomas persistentes ou novos sintomas 3 meses após a infecçªo.

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço:

Bairro:

CEP:

Telefone:

Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Manguinhos

UF: RJ

Município:

RIO DE JANEIRO

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuaçªo do Parecer: 6.693.102

Sujeitos do grupo controle saudÆvel (CS):

- ·  Indivíduos  sem  um  diagnóstico  bioquímico  de  SARS-CoV-2  e  sem  doença,  doença  aguda  ou medicamentos prescritos. PoderÆ haver a possibilidade de estes doentes terem tido SARS-CoV-2 mas nªo terem efetuado o teste. TambØm serªo incluídos indivíduos de HC com biobanco recolhidos antes do aparecimento local do SARS-CoV-2 (plasma citrato, armazenado a -80oC).

## CritØrios de Exclusªo:

- • Participantes que nªo atendam aos critØrios descritos acima;
- • Participantes que nªo conseguem fornecer seu consentimento informado.

Metodologia de AnÆlise de Dados:

MØtodos estatísticos:

- · VariÆveis demogrÆficas serªo comparadas entre sujeitos anteriormente infectados com SARS COV 2 e sofrendo COVID longa (CL+), sujeitos anteriormente infectados com SARS-COV-2 sem COVID longa (CL-) e grupo controle saudÆvel (CS) usando estatísticas convencionais.
- ·  As  variÆveis  clínicas  e  autorrelatadas  serªo  analisadas  com  aprendizado  de  maquina  (AM), reconhecimento de entidades nomeadas (REN) e pequeno/grande modelo de linguagem (SLLMs).
- · Os dados proteômicos/metabolômicos serªo analisados com aprendizado de mÆquina (AM) / anÆlises bioinformÆticas (AB).

Desfecho PrimÆrio:

O endpoint principal serÆ a identificaçªo dos subfenótipos COVID longa.

Tamanho da Amostra no Brasil: 200

Tamanho da Amostra neste Centro: 200

Grupo œnico: coleta de amostras e questionÆrio.

O Estudo Ø MulticŒntrico no Brasil? Nªo.

## Objetivo da Pesquisa:

Objetivo PrimÆrio:

O principal objetivo deste estudo serÆ identificar subfenótipos da COVID longa por meio de anÆlises de dados clínicos do paciente, juntamente com suas proteínas plasmÆticas e metabólitos.

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço:

Bairro:

CEP:

Telefone:

Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Manguinhos

UF: RJ

Município:

RIO DE JANEIRO

<!-- image -->

Continuaçªo do Parecer: 6.693.102

## Objetivos SecundÆrios:

- 1. Para determinar diferenças geogrÆficas em subfenótipos.
- 2. Determinar novos alvos terapŒuticos para reaproveitamento e/ou desenvolvimento de fÆrmacos.

## Avaliaçªo dos Riscos e Benefícios:

## Riscos:

Os riscos antecipados para os participantes que concordam em fazer parte deste estudo sªo limitados. Reconhecemos que o medo de retirar sangue pode ser uma preocupaçªo, especialmente para aqueles que tŒm transtorno de ansiedade. Nossa equipe estarÆ atenta para atender qualquer necessidade que vocŒ possa vir a ter em relaçªo a essa coleta de sangue.

## Benefícios:

Ao participar deste estudo, Ø importante destacar que vocŒ pode nªo receber benefícios diretos. No entanto, as informaçıes coletadas durante este estudo tŒm o potencial de contribuir para o desenvolvimento de tratamentos aprimorados para a COVID longa no futuro. Seus dados podem desempenhar um papel fundamental no avanço do entendimento e abordagem terapŒutica dessa condiçªo prolongada. Sua participaçªo Ø importante e pode impactar positivamente a saœde de outras pessoas no futuro. Se tiver alguma dœvida sobre o propósito ou benefícios potenciais deste estudo, a equipe do estudo estÆ disponível para fornecer mais informaçıes.

## ComentÆrios e Consideraçıes sobre a Pesquisa:

Este estudo pretende 'identificar subfenótipos da COVID longa por meio de anÆlises de dados clínicos do paciente, juntamente com suas proteínas plasmÆticas e metabólitos'. A metodologia de anÆlise de dados Ø constituída de variÆveis demogrÆficas que serªo comparadas entre participantes anteriormente infectados com SARS-COV-2 e sofrendo COVID longa (CL+), participantes anteriormente infectados com SARS-COV2 sem COVID longa (CL-) e grupo controle saudÆvel (CS) usando estatísticas convencionais.

## 3 grupos serªo incluídos:

- 1. Pessoas que tiveram COVID-19 confirmado por PCR nasofaríngeo ou teste de antígeno e evoluíram com sintomas persistentes ou novos em 3 meses após a infecçªo.
- 2. Pessoas que tiveram COVID-19 confirmado por PCR nasofaríngeo ou teste de antígeno e nªo

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço:

Bairro:

CEP:

Telefone:

Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Manguinhos

UF: RJ

Município:

RIO DE JANEIRO

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

<!-- image -->

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuaçªo do Parecer: 6.693.102

evoluíram com sintomas persistentes ou novos em 3 meses após a infecçªo.

- 3. Pessoas que nªo tiveram COVID-19 nem confirmaçªo laboratorial para SARSCOV-2 (indivíduos de controle saudÆveis).

Os dados dos pacientes com COVID longa serªo obtidos em um mínimo de 5 locais, incluindo Londres (London) e Montreal (CANADA); San Diego (EUA); Lusaka (ZAMBIA); e Rio de Janeiro (BRASIL). EstÆ prevista a inclusªo em todos os países que conduzem o estudo 5.000 participantes, e coletadas atØ 1.032 amostras de sangue para as anÆlises. Os dados clínicos serªo armazenados localmente no REDCap da Lawson Health Research Institute e os bioespØcimes serªo armazenados no Translational Research Center (TRC) do Victoria Hospital - ambos em Londres (London), OntÆrio, CanadÆ.

Pesquisa relevante, bem fundamentada, com metodologia detalhada e objetivos bem definidos. HÆ inconsistŒncia na definiçªo dos riscos ao participante da pesquisa.

Vide tópico 'Conclusıes ou PendŒncias e Lista de Inadequaçıes'.

## Consideraçıes sobre os Termos de apresentaçªo obrigatória:

AlØm da Carta de Encaminhamento ao sistema CEP/Conep, foram anexados à Plataforma Brasil os seguintes documentos considerados obrigatórios e necessÆrios (quase todos nos formatos .docx e .pdf):

- 1. Folha de Rosto;
- 2. Protocolo do Estudo versªo final 1.06 de 1 de novembro de 2023 e revisªo de literatura;
- 3. TCLE controle - Versªo final 1.06 de 01 de novembro de 2023 adaptado para o INI em 26 de fevereiro de 2024;
- 4. TCLE CL negativo - Versªo final 1.06 de 01 de novembro de 2023 adaptado para o INI em 26 de fevereiro de 2024;
- 5. TCLE CL positivo - Versªo final 1.06 de 01 de novembro de 2023 adaptado para o INI em 26 de fevereiro de 2024;
- 6. Declaraçªo do Pesquisador quanto ao cumprimento às resoluçıes 466/12, 251/97, 292/99 e 346/05;
- 7. Declaraçªo de Destino das amostras biológicas;
- 8. Declaraçªo de Infraestrutura e Instalaçıes;

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço:

Bairro:

CEP:

Telefone:

Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Manguinhos

UF: RJ

Município:

RIO DE JANEIRO

<!-- image -->

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuaçªo do Parecer: 6.693.102

- 9. Declaraçªo do pesquisador quanto ao desenho do estudo;
- 10. Declaraçªo do Pesquisador referente à finalidade dos Dados Coletados;
- 11. Orçamento do Estudo;
- 12. Regulamento do laboratório de pesquisa clínica em DST/AIDS para armazenamento de amostras biológicas;
- 13. Regimento Interno do biorrepositório LAPCLINAIDS;
- 14. QuestionÆrios GAD7, PHQ9 e PROMIS 29;
- 15. Aprovaçªo no país de origem;
- 16. Acordo entre as instituiçıes envolvidas no armazenamento e anÆlise de amostras biológicas em biorrepositório.

Os TCLE estªo adequados, detalhados e em linguagem clara e acessível.

Vide tópico 'Conclusıes ou PendŒncias e Lista de Inadequaçıes'.

## Recomendaçıes:

Vide tópico 'Conclusıes ou PendŒncias e Lista de Inadequaçıes'.

## Conclusıes ou PendŒncias e Lista de Inadequaçıes:

As seguintes pendŒncias devem ser resolvidas:

- 1) Sobre eventuais riscos aos participantes:

No projeto original e nos TCLE apresentados, o tópico referente aos potenciais riscos aos participantes nªo contempla uma eventual quebra de sigilo e da confidencialidade dos dados.

PEND˚NCIA: Incluir entre os potenciais riscos aos participantes a possibilidade de quebra de sigilo e da confidencialidade dos dados e medidas para prevenir;

## 2) Sobre a coleta de dados:

Na pÆgina 2 dos TCLE, no tópico 'O que ocorrerÆ durante sua participaçªo neste estudo?', alØm da verificaçªo do histórico mØdico e dos sintomas relacionados à Covid-19 consta a aplicaçªo de 'trŒs questionÆrios jÆ realizados na nossa coorte de COVID longa: um sobre depressªo, outro sobre ansiedade e outro sobre sua saœde geral'.

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço:

Bairro:

CEP:

Telefone:

Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Manguinhos

UF: RJ

Município:

RIO DE JANEIRO

<!-- image -->

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

<!-- image -->

Continuaçªo do Parecer: 6.693.102

TambØm consta no projeto original (item 5. PROCEDIMENTOS DE ESTUDO, subitem 5.1GLYPH&lt;9&gt;Coleta de dados, tópico 5.1.3 Dados clínicos retrospectivos/prospectivos e coleta de bioespØcimes) com o seguinte teor: 'Os participantes preencherªo os seguintes questionÆrios durante a consulta do estudo: Lista de verificaçªo de sintomas de COVID (no momento da infecçªo); Lista de verificaçªo de sintomas de COVID (no momento da consulta clínica/coleta  de  bioespØcime);  PHQ-9 (Ferramenta para medir a depressªo); TAG-7 (Ferramenta para medir transtorno de ansiedade generalizada); e PROMIS-29 (Ferramenta para medir a intensidade da dor em 7 Æreas da saœde: funçªo física, fadiga, interferŒncia da dor, sintomas depressivos, ansiedade, capacidade de participar em funçıes e atividades sociais e distœrbios do sono)'.

AN`LISE: Na Plataforma Brasil foram anexados apenas dois questionÆrios: PHQ-9 (depressªo) e GAD-7 (ansiedade). No projeto original (item 5. PROCEDIMENTOS DE ESTUDO, subitem 5.1 Coleta de dados, tópico 5.1.1 Agenda de eventos) estÆ relatado que a ferramenta PROMIS-29 serÆ aplicada apenas em San Diego (EUA) na coleta de dados clínicos retrospectivos, mas em todas as 5 cidades na coleta prospectiva dos dados.

PEND˚NCIA: Esclarecer a ausŒncia da ferramenta PROMIS-29 entre os arquivos obrigatórios anexados, ou qual questionÆrio serÆ utilizado para obtençªo de dados 'sobre sua saœde geral', conforme descrito nos TCLE.

Este projeto deverÆ ser encaminhado à Conep (`rea TemÆtica) após aprovaçªo.

## Este parecer foi elaborado baseado nos documentos abaixo relacionados:

| Tipo Documento                 | Arquivo                                          | Postagem            | Autor                   | Situaçªo   |
|--------------------------------|--------------------------------------------------|---------------------|-------------------------|------------|
| Outros                         | BIOREPOSITORIO_29fev24_ASSINTU RA_CORRIGIDA.pdf  | 29/02/2024 19:27:09 | FABIO VINICIUS DOS REIS | Aceito     |
| Informaçıes BÆsicas do Projeto | PB_INFORMA˙ÕES_B`SICAS_DO_P ROJETO_2264167.pdf   | 28/02/2024 19:46:59 |                         | Aceito     |
| Outros                         | CL_carta_encaminamento_CEP_28fev2 4_Assinado.pdf | 28/02/2024 19:45:55 | Tânia Krstic            | Aceito     |
| Outros                         | CL_carta_encaminamento_CEP_28fev2 4.docx         | 28/02/2024 19:45:33 | Tânia Krstic            | Aceito     |

21.040-900 Bairro: CEP: Manguinhos

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço:

Telefone:

Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

UF: RJ

Município: RIO DE JANEIRO

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

<!-- image -->

Continuaçªo do Parecer: 6.693.102

| Declaraçªo de Manuseio Material Biológico / Biorepositório / Biobanco   | Acordo_entre_instituicoes_armazename nto_amostras_assinado.pdf   | 28/02/2024 19:45:21   | Tânia Krstic   | Aceito   |
|-------------------------------------------------------------------------|------------------------------------------------------------------|-----------------------|----------------|----------|
| Declaraçªo de Manuseio Material Biológico / Biorepositório / Biobanco   | Acordo_entre_instituicoes_armazename nto_amostras.doc            | 28/02/2024 19:45:07   | Tânia Krstic   | Aceito   |
| Folha de Rosto                                                          | folhaDeRosto_assinado.pdf                                        | 28/02/2024 19:44:52   | Tânia Krstic   | Aceito   |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia               | TCLE_controle_26fev24_final.docx                                 | 28/02/2024 19:44:39   | Tânia Krstic   | Aceito   |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia               | TCLE_CL_positivo_26fev24_final.docx                              | 28/02/2024 15:51:47   | Tânia Krstic   | Aceito   |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia               | TCLE_CL_negativo_26fev24_final.docx                              | 28/02/2024 15:51:35   | Tânia Krstic   | Aceito   |
| Outros                                                                  | CL_aprovacao_pais_origem_port.docx                               | 19/02/2024 10:03:41   | Tânia Krstic   | Aceito   |
| Outros                                                                  | CL_aprovacao_pais_origem.pdf                                     | 19/02/2024 10:03:21   | Tânia Krstic   | Aceito   |
| Outros                                                                  | CL_revisao_literatura_02fev2024.pdf                              | 19/02/2024 10:02:42   | Tânia Krstic   | Aceito   |
| Outros                                                                  | CL_PHQ9_questionario_Portugues.pdf                               | 19/02/2024 10:02:24   | Tânia Krstic   | Aceito   |
| Outros                                                                  | CL_GAD7_questionario_Portugues.pdf                               | 19/02/2024 10:02:09   | Tânia Krstic   | Aceito   |
| Projeto Detalhado / Brochura Investigador                               | CL_Protocolo_PT_final.docx                                       | 19/02/2024 10:01:37   | Tânia Krstic   | Aceito   |
| Declaraçªo de Manuseio Material Biológico / Biorepositório / Biobanco   | CL_REGIMENTO_INTERNO_BIOREPO SITORIO_LAPCLINAIDS.pdf             | 19/02/2024 10:01:01   | Tânia Krstic   | Aceito   |
| Orçamento                                                               | CL_orcamento.xlsx                                                | 19/02/2024 09:58:18   | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                             | COVID_LONGA_Declaracao_finalidade _dados_Assinado.pdf            | 19/02/2024 09:56:00   | Tânia Krstic   | Aceito   |
| Declaraçªo de                                                           | COVID_LONGA_Declaracao_finalidade                                | 19/02/2024            | Tânia Krstic   | Aceito   |

21.040-900 Bairro: CEP: Manguinhos

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço:

Telefone:

Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

UF: RJ

Município:

RIO DE JANEIRO

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

<!-- image -->

Continuaçªo do Parecer: 6.693.102

| Pesquisadores                                                         | _dados.doc                                                              | 09:55:35            | Tânia Krstic   | Aceito   |
|-----------------------------------------------------------------------|-------------------------------------------------------------------------|---------------------|----------------|----------|
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_destino_a mostras_biologicas_Assinado.pdf        | 19/02/2024 09:55:18 | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_destino_a mostras_biologicas.doc                 | 19/02/2024 09:55:00 | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_desenho_ estudo_Assinado.pdf                     | 19/02/2024 09:54:36 | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_desenho_ estudo.doc                              | 19/02/2024 09:54:14 | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_cumprime nto_resolucoes_Assinado.pdf             | 19/02/2024 09:53:56 | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_cumprime nto_resolucoes.doc                      | 19/02/2024 09:53:19 | Tânia Krstic   | Aceito   |
| Declaraçªo de Manuseio Material Biológico / Biorepositório / Biobanco | COVID_LONGA_Regulamento_Armaze na_Amostras_Testes_Futuros_Assinado .pdf | 19/02/2024 09:53:06 | Tânia Krstic   | Aceito   |
| Declaraçªo de Manuseio Material Biológico / Biorepositório / Biobanco | COVID_LONGA_Regulamento_Armaze na_Amostras_Testes_Futuros.doc           | 19/02/2024 09:52:31 | Tânia Krstic   | Aceito   |
| Declaraçªo de Instituiçªo e Infraestrutura                            | COVID_LONGA_Declaracao_de_Infraes trutura_e_Instalacoes_Assinado.pdf    | 19/02/2024 09:52:00 | Tânia Krstic   | Aceito   |
| Declaraçªo de Instituiçªo e Infraestrutura                            | COVID_LONGA_Declaracao_de_Infraes trutura_e_Instalacoes.doc             | 19/02/2024 09:51:33 | Tânia Krstic   | Aceito   |

## Situaçªo do Parecer:

Pendente

Necessita Apreciaçªo da CONEP:

Sim

RIO DE JANEIRO, 08 de Março de 2024

MARIA CLARA GUTIERREZ GALHARDO (Coordenador(a)) Assinado por:

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço:

Bairro:

CEP:

Telefone:

Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Manguinhos

UF: RJ

Município:

RIO DE JANEIRO