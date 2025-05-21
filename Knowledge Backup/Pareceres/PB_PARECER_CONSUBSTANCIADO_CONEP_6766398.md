## COMISSˆO NACIONAL DE ÉTICA EM PESQUISA

<!-- image -->

## PARECER CONSUBSTANCIADO DA CONEP

## DADOS DO PROJETO DE PESQUISA

Pesquisador:

Título da Pesquisa: Identificaçªo de subfenótipos da COVID longa para otimizaçªo de resultados em pacientes

Instituiçªo Proponente:

Versªo:

CAAE:

Valdilea Gonçalves Veloso dos Santos

INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS -

3

77857024.0.0000.5262

`rea TemÆtica:

Pesquisas com coordenaçªo e/ou patrocínio originados fora do Brasil, excetuadas aquelas com copatrocínio do Governo Brasileiro;

Instituiçªo Proponente:

INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS -

Western University

Patrocinador Principal:

## DADOS DO PARECER

Nœmero do Parecer:

6.766.398

## Apresentaçªo do Projeto:

As informaçıes elencadas nos campos "Apresentaçªo do Projeto", "Objetivo da Pesquisa" e "Avaliaçªo dos Riscos  e  Benefícios"  foram  retiradas  do  arquivo  Informaçıes  BÆsicas  da  Pesquisa ( PB\_INFORMA˙ÕES\_B`SICAS\_DO\_PROJETO\_2264167.pdf,  de  27/03/2024).

## INTRODU˙ˆO

COVID longa refere-se à condiçªo em que as pessoas apresentam sintomas e complicaçıes persistentes após a recuperaçªo da fase aguda da COVID-19. Os dados publicados sugerem que a COVID longa contØm diversos subfenótipos e que a prevalŒncia e o impacto da COVID longa podem diferir conforme o país. A melhor compreensªo dos subfenótipos e fatores complicadores da COVID longa ajudarÆ a mobilizar e priorizar os recursos dos pacientes, estratificÆ-los para estudos de pesquisa e otimizar possíveis intervençıes.

## HIPÓTESE

Covid longa contØm diversos subfenotipos espera se obter uma melhor compreensªo dos subfenotipos e complicadores do covid longa.

## METODOLOGIA

70.719-040

(61)3315-5877

E-mail:

conep@saude.gov.br

Endereço:

Bairro:

CEP:

Telefone:

SRTVN 701, Via W 5 Norte, lote D - Edifício PO 700, 3' andar

Asa Norte

UF:

Município:

DF

BRASILIA

## COMISSˆO NACIONAL DE ÉTICA EM PESQUISA

<!-- image -->

Continuaçªo do Parecer: 6.766.398

- A) Aprendizado de mÆquina: subfenotipagem clínica: Os dados dos pacientes com COVID longa serªo obtidos em um mínimo de 5 locais, incluindo Londres, Montreal, San Diego, Lusaka e Rio de Janeiro. Os conjuntos  de  dados  de  pacientes  conterªo  atØ  540  pontos  clínicos  que  exigem  etapas  de  prØprocessamento de dados, como tratamento de valores ausentes, normalizaçªo e detecçªo de valores discrepantes. Esse processo inicial serÆ realizado utilizando o Python(v3.9.7)e bibliotecas de processamento de dados relevantes. Após o prØ-processamento, conduziremos 3 abordagens de AM:
- (1) AnÆlise Exploratória de Dados(AED) para compreender a distribuiçªo, correlaçªo e natureza dos 540 pontos de dados clínicos. TØcnicas de visualizaçªo como t-SNE e matrizes de correlaçªo serªo utilizadas para capturar padrıes e anomalias. O objetivo da AED Ø verificar a qualidade e características dos dados, facilitando a seleçªo de modelos de AM adequados;
- (2) classificadores de AM para construir um classificador Random Forest, um mØtodo de conjunto poderoso, para classificar a probabilidade dos pacientes de terem um subfenótipo específico de COVID longa com base em seus dados clínicos. A regressªo logística serÆ usada para gerar curvas ROC, a partir das quais calcularemos as pontuaçıes AUC, precisªo, recuperaçªo e F1, para fornecer uma compreensªo abrangente do desempenho do classificador;
- (3) Importância do recurso em Random Forests para obter insights mais profundos sobre variÆveis significativas relacionadas ao status do subfenótipo de COVID longa. Os principais recursos, classificados por suas pontuaçıes de importância, serªo considerados preditores potencialmente significativos e serªo submetidos a anÆlises adicionais.
- B) Reconhecimento de Entidades Nomeadas e Pequeno/Grande Modelo de Linguagem: abordagem analítica acima identificarÆ subfenótipos e características de COVID longa e serÆ complementada com duas abordagens adicionais usando os relatórios clínicos descritivos:
- (1) REN [um processo baseado em regras] e
- (2) SLLMs [desenvolvimento de prØ-treinamento e instruçıes]. AlØm disso, hÆ uma parceria com a Birlasoft/Google AI sendo explorada para duas abordagens adicionais:
- (1) Zero ou Few-Shot Learning com Med-PaLM 2 LLM para extrair recursos relevantes de nosso conjunto de dados que podem permitir que o modelo entenda e classifique dados com exemplos anteriores mínimos,

tornando-os inestimÆveis para explorar recursos que podem ser negligenciados por mØtodos convencionais;

- (2) o modelo de LLM, MedPaLM 2, serÆ contratado como colaborador de pesquisa, auxiliando na anÆlise de resultados derivados de mØtodos tradicionais de AM.

70.719-040

(61)3315-5877

E-mail:

conep@saude.gov.br

Endereço:

Bairro:

CEP:

Telefone:

SRTVN 701, Via W 5 Norte, lote D - Edifício PO 700, 3' andar

Asa Norte

UF:

Município:

DF

BRASILIA

## COMISSˆO NACIONAL DE ÉTICA EM PESQUISA

<!-- image -->

Continuaçªo do Parecer: 6.766.398

- C) AnÆlises BioinformÆticas: nosso pipeline Ø projetado especificamente para a anÆlise de dados proteômicos/NGS e metabolômicos, e Ø capaz de:
- i) identificar com precisªo os tipos de cØlulas e sua composiçªo em tecidos complexos, inferindo estÆgios de desenvolvimento celular e trajetórias pseudotemporais;
- ii) identificar vias específicas do tipo celular e mecanismos putativos numa comparaçªo fenotípica;
- iii) identificar doenças associadas a determinados padrıes de sinalizaçªo e, finalmente, associar fÆrmacos a esses padrıes. Nosso pipeline serÆ capaz de realizar a deconvoluçªo de dados de expressªo em massa para identificar a composiçªo do tipo de cØlula de cada amostra em massa. A integraçªo do nosso pipeline com dados em massa permite a criaçªo de conhecimento em nível de sistema que contØm características essenciais para o desenvolvimento celular e a exploraçªo de informaçıes valiosas disponíveis a partir de tipos específicos de cØlulas e conjuntos de dados unicelulares.
- D) Redirecionamento de fÆrmacos: Uma característica importante do nosso pipeline Ø a pesquisa de fÆrmacos, incluindo o redirecionamento de fÆrmacos. O conceito de redirecionamento de fÆrmacos baseiase no fato de que muitos fÆrmacos tŒm mœltiplos alvos moleculares e mecanismos de açªo, e seus efeitos podem se estender alØm do uso inicial pretendido.

## CRITÉRIOS DE INCLUSˆO

- - CritØrios de inclusªo de sujeitos positivos para COVID longa (CL) COVID-19 anterior (infectada por SARSCoV-2, positiva em PCR nasofaríngeo ou teste de antígeno) com COVID longa.
- - CritØrios de inclusªo de sujeitos com longo período de COVID negativa (CL-) COVID-19 anterior (infetado com SARS-CoV-2, positivo na PCR nasofaríngea ou no teste de antigØnio) sem COVID-19 longo (definido como um sujeito que confirmou a infeçªo por SARS-CoV-2 com resoluçªo completa dos sintomas e que nªo cumpre a definiçªo da OMS de sintomas persistentes ou novos sintomas 3 meses após a infeçªo.
- - Sujeitos do grupo controle saudÆvel (CS).
- -  Indivíduos  sem  um  diagnóstico  bioquímico  de  SARS-CoV-2  e  sem  doença,  doença  aguda  ou medicamentos prescritos. PoderÆ haver a possibilidade de estes doentes terem tido SARS-CoV-2 mas nªo terem efectuado o teste.
- - TambØm serªo incluídos indivíduos de HC com biobanco recolhidos antes do aparecimento local do SARSCoV-2 (plasma citrato, armazenado a - 80oC).

70.719-040

(61)3315-5877

E-mail:

conep@saude.gov.br

Endereço:

Bairro:

CEP:

Telefone:

SRTVN 701, Via W 5 Norte, lote D - Edifício PO 700, 3' andar

Asa Norte

UF:

Município:

DF

BRASILIA

Continuaçªo do Parecer: 6.766.398

## CRITÉRIOS DE EXCLUSˆO

- - Participantes que nªo atendam aos critØrios descritos acima.
- - Participantes que nªo conseguem fornecer seu consentimento informado.

## Objetivo da Pesquisa:

## OBJETIVO PRIM`RIO

O principal objetivo deste estudo serÆ identificar subfenótipos da COVID longa por meio de anÆlises de dados clínicos do paciente, juntamente com suas proteínas plasmÆticas e metabólitos.

## OBJETIVOS SECUND`RIOS

- 1. Para determinar diferenças geogrÆficas em subfenótipos.
- 2. Determinar novos alvos terapŒuticos para reaproveitamento e/ou desenvolvimento de fÆrmacos.

## Avaliaçªo dos Riscos e Benefícios:

## RISCOS

Os riscos antecipados para os participantes que concordam em fazer parte deste estudo sªo limitados. Reconhecemos que o medo de retirar sangue pode ser uma preocupaçªo, especialmente para aqueles que tŒm transtorno de ansiedade. Nossa equipe estarÆ atenta para atender qualquer necessidade que vocŒ possa vir a ter em relaçªo a essa coleta de sangue.

Riscos da coleta de sangue incluem: dor no local da entrada da agulha, manchas roxas ou vermelhidªo da pele e para algumas pessoas sensaçªo de desmaio. TambØm poderÆ ocorrer uma eventual quebra de sigilo e da confidencialidade dos dados. Para minimizar a possibilidade de risco de quebra de sigilo e assegurar a integridade e confidencialidade dos dados adotaremos as seguintes medidas: removeremos qualquer identificaçªo pessoal que possa vincular as informaçıes a um participante específico; armazenamento seguro e restriçªo de acesso aos dados, onde somente a equipe do estudo, devidamente treinada e autorizada terÆ acesso. Os dados coletados serªo utilizados exclusivamente para os propôs

## BENEF˝CIOS

Ao participar deste estudo, Ø importante destacar que vocŒ pode nªo receber benefícios

70.719-040

(61)3315-5877

E-mail:

conep@saude.gov.br

Endereço:

Bairro:

CEP:

Telefone:

SRTVN 701, Via W 5 Norte, lote D - Edifício PO 700, 3' andar

Asa Norte

UF:

Município:

DF

BRASILIA

## COMISSˆO NACIONAL DE ÉTICA EM PESQUISA

<!-- image -->

## COMISSˆO NACIONAL DE ÉTICA EM PESQUISA

<!-- image -->

Continuaçªo do Parecer: 6.766.398

diretos. No entanto, as informaçıes coletadas durante este estudo tŒm o potencial de contribuir para o desenvolvimento de tratamentos aprimorados para a COVID longa no futuro. Seus dados podem desempenhar um papel fundamental no avanço do entendimento e abordagem terapŒutica dessa condiçªo prolongada. Sua participaçªo Ø importante e pode impactar positivamente a saœde de outras pessoas no futuro. Se tiver alguma dœvida sobre o propósito ou benefícios potenciais deste estudo, a equipe do estudo estÆ disponível para fornecer mais informaçıes.

## ComentÆrios e Consideraçıes sobre a Pesquisa:

COVID longa refere-se à condiçªo em que as pessoas apresentam sintomas e complicaçıes persistentes após a recuperaçªo da fase aguda da COVID-19. Os dados publicados sugerem que a COVID longa contØm diversos subfenótipos e que a prevalŒncia e o impacto da COVID longa podem diferir conforme o país. A melhor compreensªo dos subfenótipos e fatores complicadores da COVID longa ajudarÆ a mobilizar e priorizar os recursos dos pacientes, estratificÆ-los para estudos de pesquisa e otimizar possíveis intervençıes. Os dados clínicos retrospectivos serªo coletados ao longo de 3 meses nos locais de estudo

Este Ø um estudo de coorte com trŒs braços de estudo:

- - AnÆlises de dados clínicos retrospectivos com AM/LLMs.
- - AnÆlises de bioespØcimes coletados retrospectivamente/prospectivamente com AM/AB.
- - AnÆlises de dados proteômicos/metabolômicos para descoberta de fÆrmacos com mØtodos AB/ortogonais.

Patrocinador: Western University

Financiador: Schmidt Initiative for Long COVID (SILC)

País de Origem: Estados Unidos da AmØrica

Aprovaçªo Øtica do país de origem: finalizada

HaverÆ armazenamento de material biológico em Biorrepositório: As amostras sªo enviadas à Translational Research Center (TRC) do Victoria Hospital em Londres, OntÆrio, CanadÆ que Ø responsÆvel pelo armazenamento das amostras do estudo.

70.719-040

(61)3315-5877

E-mail:

conep@saude.gov.br

Endereço:

Bairro:

CEP:

Telefone:

SRTVN 701, Via W 5 Norte, lote D - Edifício PO 700, 3' andar

Asa Norte

UF:

Município:

DF

BRASILIA

## COMISSˆO NACIONAL DE ÉTICA EM PESQUISA

Continuaçªo do Parecer: 6.766.398

## Consideraçıes sobre os Termos de apresentaçªo obrigatória:

Vide campo "Conclusıes ou PendŒncias e Lista de Inadequaçıes".

## Conclusıes ou PendŒncias e Lista de Inadequaçıes:

Nªo foram identificados óbices Øticos neste protocolo.

## Consideraçıes Finais a critØrio da CONEP:

Diante do exposto, a Comissªo Nacional de Ética em Pesquisa - Conep, de acordo com as atribuiçıes definidas na Resoluçªo CNS n' 466 de 2012 e na Norma Operacional n' 001 de 2013 do CNS, manifesta-se pela aprovaçªo do projeto de pesquisa proposto.

Situaçªo: Protocolo aprovado.

## Este parecer foi elaborado baseado nos documentos abaixo relacionados:

| Tipo Documento                                            | Arquivo                                        | Postagem            | Autor        | Situaçªo   |
|-----------------------------------------------------------|------------------------------------------------|---------------------|--------------|------------|
| Informaçıes BÆsicas do Projeto                            | PB_INFORMA˙ÕES_B`SICAS_DO_P ROJETO_2264167.pdf | 27/03/2024 18:18:14 |              | Aceito     |
| Folha de Rosto                                            | FR_assinada_27mar24.pdf                        | 27/03/2024 18:00:54 | Tânia Krstic | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia | TCLE_controle_14mar24_marcado.docx             | 15/03/2024 09:06:08 | Tânia Krstic | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia | TCLE_controle_14mar24_limpo.pdf                | 15/03/2024 09:01:02 | Tânia Krstic | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia | TCLE_CL_positivo_14mar24_marcado.d ocx         | 15/03/2024 09:00:51 | Tânia Krstic | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia | TCLE_CL_positivo_14mar24_limpo.pdf             | 15/03/2024 09:00:39 | Tânia Krstic | Aceito     |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia | TCLE_CL_negativo_14mar24_marcado. docx         | 15/03/2024 09:00:28 | Tânia Krstic | Aceito     |

70.719-040

(61)3315-5877

E-mail:

conep@saude.gov.br

Endereço:

Bairro:

CEP:

Telefone:

SRTVN 701, Via W 5 Norte, lote D - Edifício PO 700, 3' andar

Asa Norte

UF:

Município:

DF

BRASILIA

<!-- image -->

## COMISSˆO NACIONAL DE ÉTICA EM PESQUISA

<!-- image -->

Continuaçªo do Parecer: 6.766.398

| TCLE / Termos de Assentimento / Justificativa de AusŒncia             | TCLE_CL_negativo_14mar24_limpo.pdf                             | 15/03/2024 09:00:17   | Tânia Krstic                    | Aceito   |
|-----------------------------------------------------------------------|----------------------------------------------------------------|-----------------------|---------------------------------|----------|
| Outros                                                                | CL_carta_resposta_parecer_6693102_a ssinado.pdf                | 15/03/2024 09:00:01   | Tânia Krstic                    | Aceito   |
| Outros                                                                | CL_carta_resposta_parecer_6693102.d ocx                        | 15/03/2024 08:59:44   | Tânia Krstic                    | Aceito   |
| Outros                                                                | BIOREPOSITORIO_29fev24_ASSINTU RA_CORRIGIDA.pdf                | 29/02/2024 19:27:09   | FABIO VINICIUS DOS REIS MARQUES | Aceito   |
| Outros                                                                | CL_carta_encaminamento_CEP_28fev2 4_Assinado.pdf               | 28/02/2024 19:45:55   | Tânia Krstic                    | Aceito   |
| Outros                                                                | CL_carta_encaminamento_CEP_28fev2 4.docx                       | 28/02/2024 19:45:33   | Tânia Krstic                    | Aceito   |
| Declaraçªo de Manuseio Material Biológico / Biorepositório / Biobanco | Acordo_entre_instituicoes_armazename nto_amostras_assinado.pdf | 28/02/2024 19:45:21   | Tânia Krstic                    | Aceito   |
| Declaraçªo de Manuseio Material Biológico / Biorepositório / Biobanco | Acordo_entre_instituicoes_armazename nto_amostras.doc          | 28/02/2024 19:45:07   | Tânia Krstic                    | Aceito   |
| TCLE / Termos de Assentimento / Justificativa de AusŒncia             | TCLE_controle_26fev24_final.docx                               | 28/02/2024 19:44:39   | Tânia Krstic                    | Aceito   |
| TCLE / Termos de Assentimento / Justificativa de                      | TCLE_CL_positivo_26fev24_final.docx                            | 28/02/2024 15:51:47   | Tânia Krstic                    | Aceito   |
| AusŒncia TCLE / Termos de Assentimento / Justificativa de AusŒncia    | TCLE_CL_negativo_26fev24_final.docx                            | 28/02/2024 15:51:35   | Tânia Krstic                    | Aceito   |
| Outros                                                                | CL_aprovacao_pais_origem_port.docx                             | 19/02/2024 10:03:41   | Tânia Krstic                    | Aceito   |
| Outros                                                                | CL_aprovacao_pais_origem.pdf                                   | 19/02/2024 10:03:21   | Tânia Krstic                    | Aceito   |
| Outros                                                                | CL_revisao_literatura_02fev2024.pdf                            | 19/02/2024 10:02:42   | Tânia Krstic                    | Aceito   |
| Outros                                                                | CL_PHQ9_questionario_Portugues.pdf                             | 19/02/2024 10:02:24   | Tânia Krstic                    | Aceito   |
| Outros                                                                | CL_GAD7_questionario_Portugues.pdf                             | 19/02/2024 10:02:09   | Tânia Krstic                    | Aceito   |

70.719-040

(61)3315-5877

E-mail:

conep@saude.gov.br

Endereço:

Bairro:

CEP:

Telefone:

SRTVN 701, Via W 5 Norte, lote D - Edifício PO 700, 3' andar

Asa Norte

UF:

Município:

DF

BRASILIA

## COMISSˆO NACIONAL DE ÉTICA EM PESQUISA

<!-- image -->

Continuaçªo do Parecer: 6.766.398

| Projeto Detalhado / Brochura Investigador                             | CL_Protocolo_PT_final.docx                                              | 19/02/2024 10:01:37   | Tânia Krstic   | Aceito   |
|-----------------------------------------------------------------------|-------------------------------------------------------------------------|-----------------------|----------------|----------|
| Declaraçªo de Manuseio Material Biológico / Biorepositório / Biobanco | CL_REGIMENTO_INTERNO_BIOREPO SITORIO_LAPCLINAIDS.pdf                    | 19/02/2024 10:01:01   | Tânia Krstic   | Aceito   |
| Orçamento                                                             | CL_orcamento.xlsx                                                       | 19/02/2024 09:58:18   | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_finalidade _dados_Assinado.pdf                   | 19/02/2024 09:56:00   | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_finalidade _dados.doc                            | 19/02/2024 09:55:35   | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_destino_a mostras_biologicas_Assinado.pdf        | 19/02/2024 09:55:18   | Tânia Krstic   | Aceito   |
| Declaraçªo de Pesquisadores                                           | COVID_LONGA_Declaracao_destino_a mostras_biologicas.doc                 | 19/02/2024 09:55:00   | Tânia Krstic   | Aceito   |
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

70.719-040

(61)3315-5877

E-mail:

conep@saude.gov.br

Endereço:

Bairro:

CEP:

Telefone:

SRTVN 701, Via W 5 Norte, lote D - Edifício PO 700, 3' andar

Asa Norte

UF:

Município:

DF

BRASILIA

Continuaçªo do Parecer: 6.766.398

## COMISSˆO NACIONAL DE ÉTICA EM PESQUISA

BRASILIA, 22 de Abril de 2024

Laís Alves de Souza Bonilha (Coordenador(a)) Assinado por:

70.719-040

(61)3315-5877

E-mail:

conep@saude.gov.br

Endereço:

Bairro:

CEP:

Telefone:

SRTVN 701, Via W 5 Norte, lote D - Edifício PO 700, 3' andar

Asa Norte

UF:

Município:

DF

BRASILIA

<!-- image -->