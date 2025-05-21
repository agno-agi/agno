## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

## PARECER CONSUBSTANCIADO DO CEP
## DADOS DO PROJETO DE PESQUISA
Pesquisador:
Título da Pesquisa:
Instituição Proponente:
Versão:
CAAE:
IMPLEMENTAÇÃO  DE  FERRAMENTA  ELETRÔNICA  NO  PROGRAMA  DE GERENCIAMENTO DE ANTIMICROBIANOS (STEWARDSHIP) NO CENTRO HOSPITALAR DO INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS
Sandra Wagner Cardoso
INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS -
1
86318925.6.0000.5262
área Temática:
INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI/FIOCRUZ
Patrocinador Principal:
## DADOS DO PARECER
Número do Parecer:
7.407.422
Introdução
Apresentação do Projeto:
A resistência antimicrobiana é uma ameaça à saúde global, podendo contribuir para mais de cinco milhões de mortes anualmente (OMS, 2022). A multirresistência é definida como a não suscetibilidade adquirida a agentes de três ou mais categorias antimicrobianas. Bactérias Gram-positivas e Gram-negativas tem apresentado aumento da resistência antimicrobiana, entretanto as bactérias Gram-negativas altamente resistentes como Klebsiella pneumoniae produtora de carbapenemases e Acinetobacter spp., requerem atenção especial, uma vez que podem ser resistentes a todos os antimicrobianos atualmente disponíveis. (MAGIOKAROS et al, 2012). Durante os anos da pandemia de COVID-19, foi visto em todo o mundo aumento do consumo de antimicrobianos, inclusive de amplo espectro, implicando em aumento da resistência antimicrobiana. Neste período, nos Estados Unidos, o aumento de infecções por germes resistentes a carbapenêmicos foi de 35% em enterobactérias e 78% em Acinetobacter spp. (CDC, 2022). O cenário brasileiro de aumento da resistência antimicrobiana foi semelhante e em 2021 foi elaborado documento pela Anvisa com o objetivo de detecção dos casos de multirresistência nos estados brasileiros para propor estratégias para sua contenção. Aquele
## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuação do Parecer: 7.407.422
documento mostrou que o Rio de Janeiro se encontra no pior cenário, com mais de 40% das unidades de saúde com casos de multirresistência (Brasil, 2021). Diante do exposto, cabe aos serviços de saúde realizar a vigilância dos microrganismos, estabelecer medidas para prevenção de infecções relacionadas a assistência à saúde (IRAS) e buscar estratégias para o controle de antimicrobianos, com objetivo de otimizar seu  uso,  melhorando  os  desfechos  clínicos  e  minimizando  o  impacto  na  indução  de  resistência antimicrobiana (Brasil, 2023). O desenvolvimento de programa de gerenciamento do uso de antimicrobianos, ou stewardship, é uma recomendação na atenção à saúde e inclui medidas multidisciplinares para a otimização desse uso, incluindo a solicitação assertiva de exames microbiológicos, a liberação de seus resultados em tempo oportuno, a escolha do antimicrobiano mais adequado e a conformidade na prescrição em relação ao protocolo de antibioticoterapia empírica, à posologia, à dose e ao tempo de uso do antibiótico escolhido. Além disso, é importante a adesão da equipe às intervenções realizadas por infectologistas e farmacêuticos clínicos, o monitoramento de eventos adversos e o descalonamento do antimicrobiano quando indicado (BARLAM et al.,2016). Para que haja o adequado gerenciamento dos antimicrobianos, é importante estimar o consumo dos mesmos. Diferentes medidas podem ser utilizadas para realizar esta mensuração, sendo a Dose Diária Definida (Defined Daily Dose DDD) a medida de mais amplamente utilizada. No entanto, outras medidas como Dias de Terapia (Days of therapy DOT) e a Duração de Terapia (Lenght of therapy LOT), embora mais complexas de calcular, são bastante úteis para o monitoramento do uso de antimicrobianos, mostrando-se, sob certos aspectos, melhores e com relevância clínica maior que a DDD (Brasil, 2023). O cálculo da DDD relaciona o total em gramas do antimicrobiano consumido em um setor durante um determinado período, sua dose média diária usada para um adulto de 70kg (definida pela OMS) e o volume de pacientes internados (calculado através do paciente-dia do período, que é definido como medida da assistência prestada a um paciente durante o período de um dia). Uma vantagem é a facilidade na obtenção do dado, sendo a unidade recomendada pela OMS. No Brasil esse dado é de notificação mensal compulsória para ANVISA nas unidades de terapia intensiva. Esta medida, no entanto, tem limitações no que tange ao uso em pacientes pediátricos, obesos, com disfunção renal ou que, por qualquer outro motivo, estejam em uso de dose diferente da dose padronizada pela OMS ou em terapia combinada. Por este motivo, as medidas de DOT e LOT, baseadas em tempo, são fundamentais para complementar as análises quanto ao consumo de antimicrobianos. A DOT relaciona os dias de uso de um determinado antimicrobiano com o paciente-dia. É uma medida mais intuitiva e oferece maior relevância clínica e maior precisão
## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuação do Parecer: 7.407.422
na relação entre o tratamento recebido e o paciente, sendo apontada recentemente como a medida mais apropriada para a avaliar o impacto dos programas de gerenciamento dos antimicrobianos. (CISNEROS et al.,2014). A LOT, relaciona o somatório de dias de todos os antimicrobianos utilizados e o paciente-dia, fornecendo um dado mais preciso da duração da terapia antimicrobiana. A razão DOT/LOT, calculada dividindo o DOpelo LOT, é útil para avaliar a frequência em que são instituídas terapias combinadas em detrimento à monoterapia. As métricas baseadas em tempo são fundamentais porque capturam aspectos do uso de antimicrobianos que as análises baseadas apenas na quantidade, como as DDD, não conseguem refletir adequadamente. Ao considerar o tempo de tratamento, essas medidas ajudam a identificar padrões de prescrição excessiva ou inadequada, contribuindo para a otimização do uso de antimicrobianos e, consequentemente, para a prevenção da resistência antimicrobiana. Uma limitação de todos esses indicadores é o fato de não analisarem se a indicação dos antimicrobianos está correta, sendo necessário realizar também o acompanhamento deste dado para além dos cálculos das métricas de consumo. Business Intelligence é o processo de coletar, analisar e transformar dados brutos em informações úteis para apoiar a tomada de decisões estratégicas. Com o uso de ferramentas específicas, como Power BIfi, é possível monitorar indicadores, identificar oportunidades de melhoria e otimizar processos e a tomada de decisões. O software, que inicialmente foi utilizado no contexto empresarial, tem sido progressivamente incorporado à área da saúde, com o objetivo de monitorar e otimizar a gestão de recursos. (LOEWEN, et al.,2017) No Instituto Nacional de Infectologia, essa tecnologia está sendo aplicada em diversos setores, embora ainda não tenha sido implementada para o gerenciamento de antimicrobianos. Nesse contexto, a ferramenta pode ser utilizada para monitorar o uso desses medicamentos e avaliar o impacto das intervenções no controle de infecções, oferecendo uma visualização clara e objetiva dos dados. Por meio de gráficos dinâmicos e painéis personalizados, é possível que profissionais de saúde, gestores e pesquisadores acessem informações em tempo real e acompanhem o uso de antimicrobianos, observando tendências de prescrições e comparando o consumo de medicamentos entre diferentes setores, além de analisar a eficácia das estratégias de restrição e de uso otimizado de antimicrobianos. Para este estudo, selecionamos meropenem, polimixina B, vancomicina e teicoplanina para terem seu uso mensurado e auditado por serem antibióticos de amplo espectro, amplamente utilizados de forma empírica para o tratamento de IRAS em nosso país.
Continuação do Parecer: 7.407.422
## Hipótese:
Com o uso da ferramenta, será possível estimar o consumo de antimicrobianos nos diferentes setores do INI, permitindo estabelecer o padrão de consumo. Através da análise dos dados sobre as intervenções realizadas pela CCIH, será possível medir a taxa de intervenções e avaliar a taxa de aceitação das recomendações feitas aos prescritores. Indicadores de efetividade: A análise permitirá observar padrões de uso empírico versus guiado por cultura.
## Metodologia Proposta:
Este é um estudo retrospectivo, observacional, seccional, avaliando o consumo de antimicrobianos de amplo espectro no Centro Hospitalar do Instituto Nacional de Infectologia Evandro Chagas (INI), entre os meses de julho de 2024 e janeiro de 2025. A abordagem será baseada na análise dos dados de dispensação de medicamentos fornecidos para pacientes internados em enfermarias e unidades de terapia intensiva, obtidos a partir dos relatórios gerados pelo sistema de prontuário eletrônico. A metodologia será dividida em duas etapas principais: a coleta de dados e a análise desses dados com o uso da ferramenta Power BIfi. COLETA DE DADOS: Os dados necessários para a análise serão extraídos do sistema de prontuário eletrônico do hospital e do relatório de dispensação de antimicrobianos. As informações coletadas incluirão: Dados de Consumo: Registros de antibióticos de amplo espectro (meropenem, polimixina B, vancomicina e teicoplanina) prescritos para pacientes hospitalizados. Dados clínicos e microbiológicos: Para cada paciente em uso de um desses antimicrobianos, será coletada a indicação do tratamento, a ocorrência de intervenções realizadas pela equipe médica da Comissão de Controle de Infecção Hospitalar (CCIH) e a aceitação dessas intervenções pela equipe assistencial. As intervenções são realizadas pelos médicos infectologistas da CCIH sempre que são notadas, durante a discussão dos casos com os médicos prescritores, oportunidades de otimização da terapia antimicrobiana. Elas podem incluir a troca para medicamentos de maior ou menor espectro (escalonar e descalonar, respetivamente), suspensão de antibiótico ou a adequação da terapia conforme os resultados microbiológicos (terapia guiada ou baseada em cultura positiva).
Critério de Inclusão:
## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuação do Parecer: 7.407.422
Serão incluídos no estudo os dados de todas as prescrições do centro hospitalar que contenham pelo menos um dos antimicrobianos selecionados (meropenem, polimixina B, vancomicina ou teicoplanina) durante o período do estudo e que tenham sido auditadas pela CCIH.
## Critério de Exclusão:
Não há critérios de exclusão.
Metodologia de Análise de Dados:
Os dados serão coletados através de consulta ao relatório de dispensação de medicamentos e estruturados em planilha desenvolvida especificamente para o projeto. A consolidação de dados será feita utilizando Power BIfi, que permite a criação de dashboards dinâmicos para a análise visual e compreensão do consumo dos antimicrobianos. A plataforma possibilitará a visualização do perfil de uso, permitindo cálculo das métricas de consumo dos antimicrobianos.
## Desfecho Primário:
Dose Diária Definida (DDD): Quantidade (em gramas) de antimicrobiano consumido em um determinado período, normalizado para uma dose diária de referência, correlacionado com a ocupação no período em questão.
Dias  de  Tratamento  (DOT):  Número  de  dias  de  tratamento  com  um  determinado  antibiótico, correlacionado  com  a  ocupação  no  período  em  questão.
Duração de Terapia (LOT): Quantificação do tempo total de uso dos antimicrobianos, correlacionado com a ocupação no período em questão.
Razão DOT/LOT: Proporção entre os dias de tratamento e a duração total do tratamento, permitindo a análise de terapias combinadas. Avaliação das intervenções da CCIH.
## Objetivo da Pesquisa:
Objetivo Primário:
Implementar ferramenta de gerenciamento de dados para realização de auditoria do consumo de antimicrobianos de interesse especial no Centro Hospitalar do INI.
Continuação do Parecer: 7.407.422
## Objetivo Secundário:
Calcular o consumo dos antimicrobianos meropenem, polimixina B, vancomicina e teicoplanina através do DDD (dose diária definida), DOT (dias de tratamento), LOT (duração do tratamento) e razão DOT/LOT; Traçar o perfil de consumo destes antimicrobianos nos diferentes setores de internação do INI no período de julho de 2024 e janeiro de 2025: indicação do uso, necessidade de intervenção e aceitação da intervenção pela equipe Assistente.
## Avaliação dos Riscos e Benefícios:
RISCOS:
O estudo será desenvolvido de acordo com as diretrizes éticas estabelecidas pela lei N' 14.874/2024 e será apresentado para apreciação pelo Comitê de Ética do INI- Fiocruz. Os riscos envolvidos no projeto estão relacionados ao sigilo das informações acessadas para a construção do relatório dinâmico que apresentará dados agrupados e não identificados com acesso controlado por senha. Desta forma, há risco de perda da confidencialidade, que será minimizado pela anonimização dos dados.
## BENEFÍCIOS:
Este estudo permitirá compreender para quais focos infecciosos os antimicrobianos estão sendo prescritos, se o uso é empírico ou guiado por cultura, a taxa de intervenção pela CCIH e a aceitação das intervenções por parte da equipe assistencial.
## Comentários e Considerações sobre a Pesquisa:
Trata-se de estudo retrospectivo, observacional, seccional, baseado na análise de avaliando prontuários, documentos, registros, amostras ou diagnósticos para investigar o consumo de antimicrobianos de amplo espectro no Centro Hospitalar do Instituto Nacional de Infectologia Evandro Chagas (INI), entre os meses de julho de 2024 e janeiro de 2025.
O número total da amostra não foi informado.
O estudo propõe dispensa de TCLE alegando que (i) muitos dos pacientes já vieram a óbito e há difícil localização de seus familiares; (ii) alguns pacientes estão vivos, mas não mais frequentam regularmente o hospital e/ou o ambulatório; (iii) o endereço e telefone dos pacientes já não são mais os mesmos.
## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ
Continuação do Parecer: 7.407.422
Não haverá retenção de amostras.
## Considerações sobre os Termos de apresentação obrigatória:
Foram apresentados os seguintes documentos:
Declaracao\_referente\_a\_finalidade\_dos\_dados\_coletados\_RESC\_assinado.pdf
Declaracao\_de\_cumprimento\_das\_resolucoes\_do\_CNS\_RESC\_Assinado.pdf
Declaracao\_do\_Pesquisador\_quanto\_ao\_desenho\_participacao\_RESC\_assinado.pdf
TERMO\_DE\_COMPROMISSO\_confidencialidade\_E\_RESPONSABILIDADE\_RESC.pdf folhaDeRosto\_assinadoSW\_ASSINADO.PDF
PB\_INFORMAÇÕES\_BáSICAS\_DO\_PROJETO\_2474741.pdf
PROJETO\_MPPC\_INI\_RESC.docx
Dispensa\_TCLE\_ProjetoStwardship\_Assinado.pdf
## Recomendações:
Ver item ¿Conclusões, pendências e lista de inadequações¿.
## Conclusões ou Pendências e Lista de Inadequações:
1- Faz-se necessário o preenchimento do campo "Tamanho da Amostra" na Plataforma Brasil para que o documento "PB\_INFORMAÇÕES\_BáSICAS\_DO\_PROJETO\_2474741.pdf" esteja completo.
## Considerações Finais a critério do CEP:
Quando do atendimento da pendência solicitada, o projeto pode ser aprovado ad referendum.
## Este parecer foi elaborado baseado nos documentos abaixo relacionados:
Tipo Documento
Arquivo
Postagem
Autor
Situação
## INSTITUTO NACIONAL DE INFECTOLOGIA EVANDRO CHAGAS - INI / FIOCRUZ

Continuação do Parecer: 7.407.422
| Informações Básicas do Projeto                            | PB_INFORMAÇÕES_BáSICAS_DO_P ROJETO_2474741.pdf                               | 12/02/2025 07:35:38   |                                | Aceito   |
|-----------------------------------------------------------|------------------------------------------------------------------------------|-----------------------|--------------------------------|----------|
| Declaração de Pesquisadores                               | TERMO_DE_COMPROMISSO_confiden cialidade_E_RESPONSABILIDADE_RE SC.pdf         | 12/02/2025 07:33:17   | ROBERTA ESPIRITO SANTO CORREIA | Aceito   |
| TCLE / Termos de Assentimento / Justificativa de Ausência | Dispensa_TCLE_ProjetoStwardship_Ass inado.pdf                                | 12/02/2025 07:31:46   | ROBERTA ESPIRITO SANTO CORREIA | Aceito   |
| Folha de Rosto                                            | folhaDeRosto_assinadoSW_ASSINADO .PDF                                        | 12/02/2025 07:28:51   | ROBERTA ESPIRITO SANTO         | Aceito   |
| Projeto Detalhado / Brochura Investigador                 | PROJETO_MPPC_INI_RESC.docx                                                   | 05/02/2025 15:48:45   | ROBERTA ESPIRITO SANTO CORREIA | Aceito   |
| Declaração de Pesquisadores                               | Declaracao_de_cumprimento_das_resol ucoes_do_CNS_RESC_Assinado.pdf           | 13/01/2025 15:30:34   | ROBERTA ESPIRITO SANTO CORREIA | Aceito   |
| Declaração de Pesquisadores                               | Declaracao_referente_a_finalidade_dos _dados_coletados_RESC_assinado.pdf     | 13/01/2025 15:30:26   | ROBERTA ESPIRITO SANTO CORREIA | Aceito   |
| Declaração de Pesquisadores                               | Declaracao_do_Pesquisador_quanto_ao _desenho_participacao_RESC_assinad o.pdf | 13/01/2025 15:30:17   | ROBERTA ESPIRITO SANTO CORREIA | Aceito   |
## Situação do Parecer:
Pendente
Necessita Apreciação da CONEP:
Não
RIO DE JANEIRO, 24 de Fevereiro de 2025
Maria Inês Fernandes Pimentel (Coordenador(a)) Assinado por:
