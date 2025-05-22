## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

<!-- image -->

## PARECER CONSUBSTANCIADO DO CEP

## DADOS DO PROJETO DE PESQUISA

Pesquisador:

Título da Pesquisa: Identificaçªo de subfenótipos da COVID longa para otimizaçªo de resultados em pacientes

Instituiçªo Proponente:

Versªo:

CAAE:

Valdilea Gonçalves Veloso dos Santos

INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS -

2

77857024.0.0000.5262

`rea TemÆtica:

Pesquisas com coordenaçªo e/ou patrocínio originados fora do Brasil, excetuadas aquelas com copatrocínio do Governo Brasileiro;

Western University

Patrocinador Principal:

## DADOS DO PARECER

Nœmero do Parecer:

6.711.732

## Apresentaçªo do Projeto:

Os tópicos Apresentaçªo do projeto, Objetivo da Pesquisa e Avaliaçªo dos Riscos e Benefícios estªo de acordo com o documento ¿PB\_INFORMA˙ÕES\_B`SICAS\_DO\_PROJETO\_2264167.pdf¿, versªo 2, postado na Plataforma Brasil em 15/03/2024:

## Introduçªo:

COVID longa refere-se à condiçªo em que as pessoas apresentam sintomas e complicaçıes persistentes após a recuperaçªo da fase aguda da COVID-19. Os dados publicados sugerem que a COVID longa contØm diversos subfenótipos e que a prevalŒncia e o impacto da COVID longa podem diferir conforme o país. A melhor compreensªo dos subfenótipos e fatores complicadores da COVID longa ajudarÆ a mobilizar e priorizar os recursos dos pacientes, estratificÆ-los para estudos de pesquisa e otimizar possíveis intervençıes.

## Hipótese:

COVID longa contem diversos subfenotipos espera se obter uma melhor compreensªo dos subfenotipos e complicadores do COVID longa.

Metodologia proposta:

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço: Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Bairro:

CEP:

Telefone:

Manguinhos

UF: RJ

Município:

RIO DE JANEIRO

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

<!-- image -->

Continuaçªo do Parecer: 6.711.732

- A) Aprendizado de mÆquina: subfenotipagem clínica: Os dados dos pacientes com COVID longa serªo obtidos em um mínimo de 5 locais, incluindo Londres, Montreal, San Diego, Lusaka e Rio de Janeiro. Os conjuntos  de  dados  de  pacientes  conterªo  atØ  540  pontos  clínicos  que  exigem  etapas  de  prØprocessamento de dados, como tratamento de valores ausentes, normalizaçªo e detecçªo de valores discrepantes.  Esse  processo  inicial  serÆ  realizado  utilizando  o  Python  (v  3.9.7)  e  bibliotecas  de processamento de dados relevantes. Após o prØ-processamento, conduziremos 3 abordagens de AM: (1) AnÆlise Exploratória de Dados (AED) para compreender a distribuiçªo, correlaçªo e natureza dos 540 pontos de dados clínicos. TØcnicas de visualizaçªo como t-SNE e matrizes de correlaçªo serªo utilizadas para capturar padrıes e anomalias. O objetivo da AED Ø verificar a qualidade e características dos dados, facilitando a seleçªo de modelos de AM adequados;
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

Continuaçªo do Parecer: 6.711.732

- (2) O modelo de LLM, Med-PaLM 2, serÆ contratado como ¿colaborador de pesquisa¿, auxiliando na anÆlise de resultados derivados de mØtodos tradicionais de AM.
- C) AnÆlises BioinformÆticas: nosso pipeline Ø projetado especificamente para a anÆlise de dados proteômicos/NGS e metabolômicos, e Ø capaz de:
- i) identificar com precisªo os tipos de cØlulas e sua composiçªo em tecidos complexos, inferindo estÆgios de desenvolvimento celular e trajetórias pseudotemporais;
- ii) identificar vias específicas do tipo celular e mecanismos putativos numa comparaçªo fenotípica; e
- iii) identificar doenças associadas a determinados padrıes de sinalizaçªo e, finalmente, associar fÆrmacos a esses padrıes. Nosso pipeline serÆ capaz de realizar a deconvoluçªo de dados de expressªo em massa para identificar a composiçªo do tipo de cØlula de cada amostra em massa. A integraçªo do nosso pipeline com dados em massa permite a criaçªo de conhecimento em nível de sistema que contØm características essenciais para o desenvolvimento celular e a exploraçªo de informaçıes valiosas disponíveis a partir de tipos específicos de cØlulas e conjuntos de dados unicelulares.
- D) Redirecionamento de fÆrmacos: Uma característica importante do nosso pipeline Ø a pesquisa de fÆrmacos, incluindo o redirecionamento de fÆrmacos. O conceito de redirecionamento de fÆrmacos baseiase no fato de que muitos fÆrmacos tŒm mœltiplos alvos moleculares e mecanismos de açªo, e seus efeitos podem se estender alØm do uso inicial pretendido.

## CritØrios de Inclusªo:

CritØrios de inclusªo de sujeitos positivos para COVID longa (CL):

¿ COVID-19 anterior (infectada por SARS-CoV-2, positiva em PCR nasofaríngeo ou teste de antígeno) com COVID longa.

CritØrios de inclusªo de sujeitos com longo período de COVID negativa (CL-):

- ¿ COVID-19 anterior (infetado com SARS-CoV-2, positivo na PCR nasofaríngea ou no teste de antígeno) sem COVID-19 longo (definido como um sujeito que confirmou a infecçªo por SARS-CoV-2 com resoluçªo completa dos sintomas e que nªo cumpre a definiçªo da OMS de sintomas persistentes ou novos sintomas 3 meses após a infecçªo.

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

Continuaçªo do Parecer: 6.711.732

Sujeitos do grupo controle saudÆvel (CS):

- ¿  Indivíduos  sem  um  diagnóstico  bioquímico  de  SARS-CoV-2  e  sem  doença,  doença  aguda  ou medicamentos prescritos. PoderÆ haver a possibilidade de estes doentes terem tido SARS-CoV-2 mas nªo terem efetuado o teste. TambØm serªo incluídos indivíduos de HC com biobanco recolhidos antes do aparecimento local do SARS-CoV-2 (plasma citrato, armazenado a -80oC).

## CritØrios de Exclusªo:

- ¿ Participantes que nªo atendam aos critØrios descritos acima;
- ¿ Participantes que nªo conseguem fornecer seu consentimento informado.

Metodologia de AnÆlise de Dados:

MØtodos estatísticos:

- ¿ VariÆveis demogrÆficas serªo comparadas entre sujeitos anteriormente infectados com SARS COV 2 e sofrendo COVID longa (CL+), sujeitos anteriormente infectados com SARS-COV-2 sem COVID longa (CL¿) e grupo controle saudÆvel (CS) usando estatísticas convencionais.
- ¿  As  variÆveis  clínicas  e  autorrelatadas  serªo  analisadas  com  aprendizado  de  maquina  (AM), reconhecimento de entidades nomeadas (REN) e pequeno/grande modelo de linguagem (SLLMs). ¿ Os dados proteômicos/metabolômicos serªo analisados com aprendizado de mÆquina (AM) / anÆlises bioinformÆticas (AB).

Desfecho PrimÆrio:

O endpoint principal serÆ a identificaçªo dos subfenótipos COVID longa.

Tamanho da Amostra no Brasil: 200

Tamanho da Amostra neste Centro: 200

Grupo œnico: coleta de amostras e questionÆrio.

O Estudo Ø MulticŒntrico no Brasil? Nªo.

## Objetivo da Pesquisa:

Objetivo PrimÆrio:

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço: Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Bairro:

CEP:

Telefone:

Manguinhos

UF: RJ

Município:

RIO DE JANEIRO

<!-- image -->

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

<!-- image -->

Continuaçªo do Parecer: 6.711.732

O principal objetivo deste estudo serÆ identificar subfenótipos da COVID longa por meio de anÆlises de dados clínicos do paciente, juntamente com suas proteínas plasmÆticas e metabólitos.

## Objetivos SecundÆrios:

- 1. Para determinar diferenças geogrÆficas em subfenótipos.
- 2. Determinar novos alvos terapŒuticos para reaproveitamento e/ou desenvolvimento de fÆrmacos.

## Avaliaçªo dos Riscos e Benefícios:

Riscos:

Os riscos antecipados para os participantes que concordam em fazer parte deste estudo sªo limitados. Reconhecemos que o medo de retirar sangue pode ser uma preocupaçªo, especialmente para aqueles que tŒm transtorno de ansiedade. Nossa equipe estarÆ atenta para atender qualquer necessidade que vocŒ possa vir a ter em relaçªo a essa coleta de sangue.

Riscos da coleta de sangue incluem: dor no local da entrada da agulha, manchas roxas ou vermelhidªo da pele e para algumas pessoas sensaçªo de desmaio. TambØm poderÆ ocorrer uma eventual quebra de sigilo e da confidencialidade dos dados. Para minimizar a possibilidade de risco de quebra de sigilo e assegurar a integridade e confidencialidade dos dados adotaremos as seguintes medidas: removeremos qualquer identificaçªo pessoal que possa vincular as informaçıes a um participante específico; armazenamento seguro e restriçªo de acesso aos dados, onde somente a equipe do estudo, devidamente treinada e autorizada terÆ acesso. Os dados coletados serªo utilizados exclusivamente para os propósitos delineados no protocolo de pesquisa, nªo sendo compartilhados ou utilizados para outros fins sem o consentimento explícito dos participantes.

## Benefícios:

Ao participar deste estudo, Ø importante destacar que o participante pode nªo receber benefícios diretos. No entanto, as informaçıes coletadas durante este estudo tŒm o potencial de contribuir para o desenvolvimento de  tratamentos  aprimorados  para  a  COVID  longa  no  futuro.  Os  dados  dos  participantes  podem desempenhar um papel fundamental no avanço do entendimento e abordagem terapŒutica dessa condiçªo prolongada.

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

Continuaçªo do Parecer: 6.711.732

## ComentÆrios e Consideraçıes sobre a Pesquisa:

Este estudo pretende ¿identificar subfenótipos da COVID longa por meio de anÆlises de dados clínicos do paciente, juntamente com suas proteínas plasmÆticas e metabólitos¿. A metodologia de anÆlise de dados Ø constituída de variÆveis demogrÆficas que serªo comparadas entre participantes anteriormente infectados com SARS-COV-2 e sofrendo COVID longa (CL+), participantes anteriormente infectados com SARS-COV2 sem COVID longa (CL¿) e grupo controle saudÆvel (CS) usando estatísticas convencionais.

Trata-se de respostas às pendŒncias contidas no Parecer Consubstanciado n. 6.693.102, emitido em 08/03/2024.

Vide tópico ¿Conclusıes ou PendŒncias e Lista de Inadequaçıes¿.

## Consideraçıes sobre os Termos de apresentaçªo obrigatória:

Foram anexados à Plataforma Brasil os seguintes documentos:

- 1. CL\_carta\_resposta\_parecer\_6693102 (formatos em .docx e .pdf);
- 2. TCLE\_CL\_negativo\_14mar24 (marcado e limpo);
- 3. TCLE\_CL\_positivo\_14mar24 (marcado e limpo);
- 4. TCLE\_controle\_14mar24 (marcado e limpo);
- 5. PB\_INFORMA˙ÕES\_B`SICAS\_DO\_PROJETO\_2264167.pdf.

Vide tópico ¿Conclusıes ou PendŒncias e Lista de Inadequaçıes¿.

## Recomendaçıes:

Vide tópico ¿Conclusıes ou PendŒncias e Lista de Inadequaçıes¿.

## Conclusıes ou PendŒncias e Lista de Inadequaçıes:

No Parecer Consubstanciado n. 6.693.102 as seguintes pendŒncias foram assinaladas:

- 1) Sobre eventuais riscos aos participantes:

No projeto original e nos TCLE apresentados, o tópico referente aos potenciais riscos aos participantes nªo contempla uma eventual quebra de sigilo e da confidencialidade dos dados.

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço: Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Bairro:

CEP:

Telefone:

Manguinhos

UF: RJ

Município:

RIO DE JANEIRO

<!-- image -->

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

<!-- image -->

Continuaçªo do Parecer: 6.711.732

PEND˚NCIA: Incluir entre os potenciais riscos aos participantes a possibilidade de quebra de sigilo e da confidencialidade dos dados e medidas para prevenir;

RESPOSTA: No TCLE foi acrescentado ao item riscos o seguinte texto em destaque abaixo:

## Riscos e restriçıes

Os riscos antecipados para os participantes que concordam em fazer parte deste estudo sªo limitados. Reconhecemos que o medo de retirar sangue pode ser uma preocupaçªo, especialmente para aqueles que tŒm transtorno de ansiedade. Nossa equipe estarÆ atenta para atender qualquer necessidade que vocŒ possa vir a ter em relaçªo a essa coleta de sangue. Riscos da coleta de sangue incluem: dor no local da entrada da agulha, manchas roxas ou vermelhidªo da pele e para algumas pessoas sensaçªo de desmaio. TambØm poderÆ ocorrer uma eventual quebra de sigilo e da confidencialidade dos dados. Para minimizar a possibilidade de risco de quebra de sigilo e assegurar a integridade e confidencialidade dos dados adotaremos as seguintes medidas: removeremos qualquer identificaçªo pessoal que possa vincular as informaçıes a um participante específico; armazenamento seguro e restriçªo de acesso aos dados, onde somente a equipe do estudo, devidamente treinada e autorizada terÆ acesso. Os dados coletados serªo utilizados  exclusivamente  para  os  propósitos  delineados  no  protocolo  de  pesquisa,  nªo  sendo compartilhados  ou  utilizados  para  outros  fins  sem  o  consentimento  explícito  dos  participantes.

AN`LISE E CONCLUSˆO: O texto foi incluído em todos os TCLE e no documento Informaçıes BÆsicas do Projeto na Plataforma Brasil. PEND˚NCIA ATENDIDA.

## 2) Sobre a coleta de dados:

Na pÆgina 2 dos TCLE, no tópico 'O que ocorrerÆ durante sua participaçªo neste estudo?¿, alØm da verificaçªo do histórico mØdico e dos sintomas relacionados à Covid-19 consta a aplicaçªo de ¿trŒs questionÆrios jÆ realizados na nossa coorte de COVID longa: um sobre depressªo, outro sobre ansiedade e outro sobre sua saœde geral¿.

TambØm consta no projeto original (item 5. PROCEDIMENTOS DE ESTUDO, subitem 5.1GLYPH&lt;9&gt;Coleta de dados, tópico 5.1.3 Dados clínicos retrospectivos/prospectivos e coleta de bioespØcimes) com o seguinte teor: ¿Os participantes preencherªo os seguintes questionÆrios durante a consulta do estudo: Lista de verificaçªo de sintomas de COVID (no momento da infecçªo); Lista de verificaçªo de

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

Continuaçªo do Parecer: 6.711.732

sintomas de COVID (no momento da consulta clínica/coleta de bioespØcime); PHQ-9 (Ferramenta para medir a depressªo); TAG-7 (Ferramenta para medir transtorno de ansiedade generalizada); e PROMIS-29 (Ferramenta para medir a intensidade da dor em 7 Æreas da saœde: funçªo física, fadiga, interferŒncia da dor, sintomas depressivos, ansiedade, capacidade de participar em funçıes e atividades sociais e distœrbios do sono)¿.

AN`LISE: Na Plataforma Brasil foram anexados apenas dois questionÆrios: PHQ-9 (depressªo) e GAD-7 (ansiedade). No projeto original (item 5. PROCEDIMENTOS DE ESTUDO, subitem 5.1 Coleta de dados, tópico 5.1.1 Agenda de eventos) estÆ relatado que a ferramenta PROMIS-29 serÆ aplicada apenas em San Diego (EUA) na coleta de dados clínicos retrospectivos, mas em todas as 5 cidades na coleta prospectiva dos dados.

PEND˚NCIA: Esclarecer a ausŒncia da ferramenta PROMIS-29 entre os arquivos obrigatórios anexados, ou qual questionÆrio serÆ utilizado para obtençªo de dados ¿sobre sua saœde geral¿, conforme descrito nos TCLE.

RESPOSTA: Os questionÆrios jÆ estavam contidos no item 8 - apŒndice do protocolo. Feito com detalhamento abaixo:

PÆgina do protocoloGLYPH&lt;9&gt;QuestionÆrio

19GLYPH&lt;9&gt;GLYPH&lt;9&gt;GLYPH&lt;9&gt;GAD 7

22GLYPH&lt;9&gt;GLYPH&lt;9&gt;GLYPH&lt;9&gt;PROMIS 29

29GLYPH&lt;9&gt;GLYPH&lt;9&gt;GLYPH&lt;9&gt;PHQ 9

PorØm para melhor visualizaçªo foi colocado tambØm como arquivo anexo.

## CONCLUSˆO: PEND˚NCIA ATENDIDA.

Este relatório pode ser aprovado ad referendum.

Este projeto serÆ encaminhado à Conep (`rea TemÆtica) após aprovaçªo.

## Consideraçıes Finais a critØrio do CEP:

O projeto serÆ encaminhado à Conep (`rea TemÆtica).

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço: Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Bairro:

CEP:

Telefone:

Manguinhos

UF: RJ

Município:

RIO DE JANEIRO

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

<!-- image -->

Continuaçªo do Parecer: 6.711.732

## O presente projeto, seguiu nesta data para anÆlise da CONEP e só tem o seu início autorizado após a aprovaçªo pela mesma.

## Este parecer foi elaborado baseado nos documentos abaixo relacionados:

| Tipo Documento                                                     | Arquivo                                                        | Postagem            | Autor                           | Situaçªo   |
|--------------------------------------------------------------------|----------------------------------------------------------------|---------------------|---------------------------------|------------|
| Informaçıes BÆsicas do Projeto                                     | PB_INFORMA˙ÕES_B`SICAS_DO_P ROJETO_2264167.pdf                 | 15/03/2024 09:06:41 |                                 | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia          | TCLE_controle_14mar24_marcado.docx                             | 15/03/2024 09:06:08 | Tânia Krstic                    | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia          | TCLE_controle_14mar24_limpo.pdf                                | 15/03/2024 09:01:02 | Tânia Krstic                    | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia          | TCLE_CL_positivo_14mar24_marcado.d ocx                         | 15/03/2024 09:00:51 | Tânia Krstic                    | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia          | TCLE_CL_positivo_14mar24_limpo.pdf                             | 15/03/2024 09:00:39 | Tânia Krstic                    | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de                   | TCLE_CL_negativo_14mar24_marcado. docx                         | 15/03/2024 09:00:28 | Tânia Krstic                    | Aceito     |
| AusŒncia TCLE / Termos de Assentimento / Justificativa de AusŒncia | TCLE_CL_negativo_14mar24_limpo.pdf                             | 15/03/2024 09:00:17 | Tânia Krstic                    | Aceito     |
| Outros                                                             | CL_carta_resposta_parecer_6693102_a ssinado.pdf                | 15/03/2024 09:00:01 | Tânia Krstic                    | Aceito     |
| Outros                                                             | CL_carta_resposta_parecer_6693102.d ocx                        | 15/03/2024 08:59:44 | Tânia Krstic                    | Aceito     |
| Outros                                                             | BIOREPOSITORIO_29fev24_ASSINTU RA_CORRIGIDA.pdf                | 29/02/2024 19:27:09 | FABIO VINICIUS DOS REIS MARQUES | Aceito     |
| Outros                                                             | CL_carta_encaminamento_CEP_28fev2 4_Assinado.pdf               | 28/02/2024 19:45:55 | Tânia Krstic                    | Aceito     |
| Outros                                                             | CL_carta_encaminamento_CEP_28fev2 4.docx                       | 28/02/2024 19:45:33 | Tânia Krstic                    | Aceito     |
| Declaraçªo de Manuseio Material Biológico / Biorepositório /       | Acordo_entre_instituicoes_armazename nto_amostras_assinado.pdf | 28/02/2024 19:45:21 | Tânia Krstic                    | Aceito     |

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço: Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Bairro:

CEP:

Telefone:

Manguinhos

UF: RJ

Município: RIO DE JANEIRO

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

<!-- image -->

Continuaçªo do Parecer: 6.711.732

| Biobanco                                                              | Acordo_entre_instituicoes_armazename nto_amostras_assinado.pdf   | 28/02/2024 19:45:21   | Tânia Krstic   | Aceito   |
|-----------------------------------------------------------------------|------------------------------------------------------------------|-----------------------|----------------|----------|
| Declaraçªo de Manuseio Material Biológico / Biorepositório / Biobanco | Acordo_entre_instituicoes_armazename nto_amostras.doc            | 28/02/2024 19:45:07   | Tânia Krstic   | Aceito   |
| Folha de Rosto                                                        | folhaDeRosto_assinado.pdf                                        | 28/02/2024 19:44:52   | Tânia Krstic   | Aceito   |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia             | TCLE_controle_26fev24_final.docx                                 | 28/02/2024 19:44:39   | Tânia Krstic   | Aceito   |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia             | TCLE_CL_positivo_26fev24_final.docx                              | 28/02/2024 15:51:47   | Tânia Krstic   | Aceito   |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia             | TCLE_CL_negativo_26fev24_final.docx                              | 28/02/2024 15:51:35   | Tânia Krstic   | Aceito   |
| Outros                                                                | CL_aprovacao_pais_origem_port.docx                               | 19/02/2024 10:03:41   | Tânia Krstic   | Aceito   |
| Outros                                                                | CL_aprovacao_pais_origem.pdf                                     | 19/02/2024 10:03:21   | Tânia Krstic   | Aceito   |
| Outros                                                                | CL_revisao_literatura_02fev2024.pdf                              | 19/02/2024 10:02:42   | Tânia Krstic   | Aceito   |
| Outros                                                                | CL_PHQ9_questionario_Portugues.pdf                               | 19/02/2024 10:02:24   | Tânia Krstic   | Aceito   |
| Outros                                                                | CL_GAD7_questionario_Portugues.pdf                               | 19/02/2024 10:02:09   | Tânia Krstic   | Aceito   |
| Projeto Detalhado / Brochura Investigador                             | CL_Protocolo_PT_final.docx                                       | 19/02/2024 10:01:37   | Tânia Krstic   | Aceito   |
| Declaraçªo de Manuseio Material Biológico / Biorepositório / Biobanco | CL_REGIMENTO_INTERNO_BIOREPO SITORIO_LAPCLINAIDS.pdf             | 19/02/2024 10:01:01   | Tânia Krstic   | Aceito   |
| Orçamento                                                             | CL_orcamento.xlsx                                                | 19/02/2024 09:58:18   | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_finalidade _dados_Assinado.pdf            | 19/02/2024 09:56:00   | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_finalidade _dados.doc                     | 19/02/2024 09:55:35   | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_destino_a mostras_biologicas_Assinado.pdf | 19/02/2024 09:55:18   | Tânia Krstic   | Aceito   |

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço: Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Bairro:

CEP:

Telefone:

Manguinhos

UF: RJ

Município:

RIO DE JANEIRO

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

<!-- image -->

Continuaçªo do Parecer: 6.711.732

| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_destino_a mostras_biologicas.doc                 | 19/02/2024 09:55:00   | Tânia Krstic   | Aceito   |
|-----------------------------------------------------------------------|-------------------------------------------------------------------------|-----------------------|----------------|----------|
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_desenho_ estudo_Assinado.pdf                     | 19/02/2024 09:54:36   | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_desenho_ estudo.doc                              | 19/02/2024 09:54:14   | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_cumprime nto_resolucoes_Assinado.pdf             | 19/02/2024 09:53:56   | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_cumprime nto_resolucoes.doc                      | 19/02/2024 09:53:19   | Tânia Krstic   | Aceito   |
| Declaraçªo de Manuseio Material Biológico / Biorepositório / Biobanco | COVID_LONGA_Regulamento_Armaze na_Amostras_Testes_Futuros_Assinado .pdf | 19/02/2024 09:53:06   | Tânia Krstic   | Aceito   |
| Declaraçªo de Manuseio Material Biológico / Biorepositório / Biobanco | COVID_LONGA_Regulamento_Armaze na_Amostras_Testes_Futuros.doc           | 19/02/2024 09:52:31   | Tânia Krstic   | Aceito   |
| Declaraçªo de Instituiçªo e Infraestrutura                            | COVID_LONGA_Declaracao_de_Infraes trutura_e_Instalacoes_Assinado.pdf    | 19/02/2024 09:52:00   | Tânia Krstic   | Aceito   |
| Declaraçªo de Instituiçªo e Infraestrutura                            | COVID_LONGA_Declaracao_de_Infraes trutura_e_Instalacoes.doc             | 19/02/2024 09:51:33   | Tânia Krstic   | Aceito   |

## Situaçªo do Parecer:

Aprovado

Necessita Apreciaçªo da CONEP:

Sim

RIO DE JANEIRO, 19 de Março de 2024

Maria InŒs Fernandes Pimentel (Coordenador(a)) Assinado por:

21.040-900

(21)3865-9585

E-mail:

cep@ini.fiocruz.br

Endereço: Avenida Brasil 4365, sala 102 do andar tØrreo do Pavilhªo JosØ Rodrigues da Silva

Bairro:

CEP:

Telefone:

Manguinhos

UF: RJ

Município:

RIO DE JANEIRO