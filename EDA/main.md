                                                                        Energy & Buildings 303 (2024) 113823


                                                                      Contents lists available at ScienceDirect


                                                                         Energy & Buildings
                                                           journal homepage: www.elsevier.com/locate/enbuild




Identiﬁcation of representative building archetypes: A novel approach
using multi-parameter cluster analysis applied to the Swedish residential
building stock
Lukas Dahlström a,∗ , Fatemeh Johari b , Tor Broström c , Joakim Widén b
a
  Division of Civil Engineering and Built Environment, Department of Civil and Industrial Engineering, Uppsala University Campus Gotland, 621 57 Visby, Sweden
b
  Division of Civil Engineering and Built Environment, Department of Civil and Industrial Engineering, Uppsala University, 751 04 Uppsala, Sweden
c
  Division of Conservation, Department of Art History, Uppsala University Campus Gotland, 621 57 Visby, Sweden




A B S T R A C T

Building archetype identiﬁcation is crucial for Urban Building Energy Modeling (UBEM), but is still considered one of the biggest challenges in this ﬁeld. New
methods of data acquisition, along with data mining techniques such as clustering, have recently received attention for the possibility of signiﬁcantly increasing
identiﬁcation reliability and archetype accuracy. This paper aims to establish a new and simple clustering methodology for developing building archetypes for hybrid
UBEM, using open data sets and multiple diverse variables, that is still reliable and possible to validate without the use of metered energy use or real building data.
The methodology uses k-means clustering for 10 building parameters simultaneously, including socio-economic parameters obtained using spatial interpolation of
statistical values. Building archetypes are successfully developed for the residential building stocks of two case study areas in Sweden. The results also show that the
error metric values for multiple iterations diverge after a certain number of clusters, even when using the same clustering methodology on the same data set. This
discovered eﬀect, along with the combined use of one well-known and one novel error metric, constitutes a framework well adapted to accurately determining the
optimal number of building archetypes.




1. Introduction and background                                                                    1.1. Urban Building Energy Modeling and archetype development

                                                                                                      Detailed simulations of the energy demand in buildings are essential
    The building sector plays an integral role in the energy systems
                                                                                                  for well-informed policy decisions regarding sustainability measures or
of our present society, where the energy use in households currently
                                                                                                  strategies for energy transition. With well designed models, accurate
accounts for 28% of the total energy use in the EU [1]. Urban areas ac-                           predictions can be made. Scenarios regarding proposed measures or the
count for more than 70% of global carbon dioxide emissions associated                             impact of external factors on the energy system can be simulated with
with energy use [2] and with the current overall population growth,                               high precision, which could be of high importance when determining
urban population will have increased by 50% by 2050 as urbanisation                               future building energy performance or designing new urban energy sys-
increases worldwide [3]. The EU has set ambitious targets for mitigat-                            tems [7].
ing climate change where the built environment in cities is expected                                  In Building energy modelling (BEM), the fundamental approach
to play an essential role, including reducing greenhouse gas emissions                            is to quantify the energy performance of the building for diﬀerent
by 40% and improving energy eﬃciency by at least 32.5% compared to                                spatio-temporal resolutions. The energy performance is determined by
1990’s levels [4]. In response to the growing urbanisation rate, and with                         multiple factors, such as building characteristics, occupant behaviour,
the prospect of climate change, it is necessary to develop urban plan-                            climate and location. For city-scale applications, simulating thousands
ning towards more sustainable strategies and to further include energy                            of buildings at a high spatio-temporal scale quickly becomes data-
planning with interconnected solutions [5]. The need for implementing                             intensive and computationally heavy. This is a challenge for city-scale
integrated energy planning in cities along with the key role of build-                            building energy simulations, that is commonly addressed by applying
ings in the urban energy balance has led to the emergence of city-scale                           several diﬀerent grouping and clustering techniques. Instead of data
building-oriented studies [6].                                                                    collection and model characterisation for each individual building, a


    * Corresponding author.
      E-mail address: lukas.dahlstrom@angstrom.uu.se (L. Dahlström).

https://doi.org/10.1016/j.enbuild.2023.113823
Received 28 February 2023; Received in revised form 23 November 2023; Accepted 4 December 2023
Available online 13 December 2023
0378-7788/© 2023 The Author(s). Published by Elsevier B.V. This is an open access article under the CC BY license (http://creativecommons.org/licenses/by/4.0/).
L. Dahlström, F. Johari, T. Broström et al.                                                                                 Energy & Buildings 303 (2024) 113823


subset of representative buildings, i.e. building archetypes, can be cre-        on some variables, producing an un-biased grouping result. Using clus-
ated which are later used for upscaling. This abstraction of the building        ter analysis for building archetype development is rapidly growing in
stock is a useful and often necessary approach for large-scale applica-          UBEM and is a promising area for further improvements in classiﬁca-
tions, and has also been proven useful regarding other functions such as         tion and model accuracy [7].
model transferability, compression or explanation of information, and
energy performance benchmarking [8].                                             1.2. Cluster analysis
     Using archetypes can however increase the risk of model over-
simpliﬁcation, and is currently associated with the largest uncertainty              A multitude of clustering methods and algorithms have been pre-
for building energy simulations [9,10]. Further, an assumption made              sented, with four categories being most common in the literature: parti-
when using archetypes is that they are representative for all building           tional clustering, hierarchical clustering, density-based clustering, and
parameters, including for instance construction materials, U-values and          grid-based clustering [13]. Two of the most commonly used algorithms
electricity use, and not only the parameters present in the segmentation         are the k-means algorithm, which is a partitional clustering method,
or clustering process.                                                           and the Agglomerative hierarchical clustering (AHC) method.
     City-scale, bottom-up engineering based modelling of heat and mass              The k-means algorithm is complex but computationally fast. It is
ﬂows to simulate the energy performance of buildings is commonly re-             based on Euclidean distance, which is usually successful in ﬁnding clus-
ferred to as Urban Building Energy Modeling (UBEM) [9]. In recent                ters even with a high number of clustering parameters; however, it is
UBEM research the hybrid approach is however becoming increasingly               not capable of analysing arbitrarily shaped clusters [13]. Ghiassi and
common, rather than the purely bottom-up (physical) approach. In                 Mahdavi [11] analysed a multitude of scenarios and successfully cre-
hybrid models the buildings are modelled after their physical charac-            ated accurate representative buildings with up to 12 clustering param-
teristics, while data such as building air leakage or occupancy, which           eters. For identiﬁcation of representative buildings, Tardioli et al. [14]
are typically stochastic parameters, are being treated as in statistical         evaluated multiple clustering algorithms with diﬀerent normalisation
models. This creates empirical distributions of the uncertain parame-            approaches and validation indices. They found that k-means was the
ters and therefore the model can make use of both deterministic and              method that performed best for residential multi-family buildings. The
probabilistic processes. Hybrid models solve many of the shortcomings            algorithm has also been proved to perform better than AHC to identify
of physical models, but previous literature reviews argue that there are         sub-groups of energy consumption in buildings [15] and for thermal
still some signiﬁcant knowledge gaps that should be subject to further           zoning and load pattern analysis for oﬃce buildings [16]. Apart from
research, particularly archetype development [6,7].                              ﬁnding representative buildings, k-means has been demonstrated to be
     The process of archetype development typically includes three steps:        a useful algorithm for segmenting energy use groups [17]. Evaluat-
classiﬁcation (or segmentation), characterisation, and calibration.              ing clustering-based methods for simulating the annual heat demand
     Classiﬁcation involves categorising the buildings into sub-groups to        or peak heat demand, De Jaeger et al. [18] found that k-means clus-
better represent the diﬀerences in typology or simulation behaviour.             tering combined with re-scaling standardisation techniques yielded the
Typical parameters for segmentation are building age, use, size, or sim-         lowest root mean square error for all key performance indicators tested,
ilar. After classiﬁcation of the building stock, the identiﬁed archetypes        indicating that it gives the best clustering result. Gangolells et al. [19]
need to be characterised by all relevant building parameters, not                successfully used the algorithm to ﬁnd representative buildings using
only those used for segmentation. These parameters are usually non-              an Energy performance certiﬁcate (EPC) database for a large set of of-
geometric, which might include construction materials, occupancy, and            ﬁce and mixed use buildings, gaining highly representative archetypes.
heating, ventilation and air conditioning (HVAC) systems.                        Hsu [15] analysed and compared recent work using clustering tech-
     For classiﬁcation and characterisation of archetypes there are also         niques to identify sub-groups of energy consumption in buildings.
three major approaches: deterministic, probabilistic or using cluster            The study concludes that 𝑘-means gives less accurate predictions than
analysis. With a deterministic approach, a building is classiﬁed accord-         cluster-wise regression but more stable clusters when the value of 𝑘 is
ing to its theoretical energy use which is directly determined by input          chosen, and that there is a trade-oﬀ between prediction accuracy and
parameter values. This categorisation is simple to perform with gen-             cluster stability. The value of k is however chosen arbitrarily, with-
eral building data and knowledge of building physics. However, this              out any underlying reasoning or methodology, which may undermine
approach can be too simpliﬁed and generic and misrepresent the real              this conclusion. One of the most common problems faced when using
diversity of the building stock, which may result in inaccurate energy           k-means clustering is to determine the optimal number of clusters, as
demand patterns [6]. Building archetype characteristics are typically            the clustering algorithm has the desired number of clusters as an input
represented by a set of ﬁxed values per archetype or with values lin-            value, not as a result [11,13,17,18].
early dependent on geometric parameters.
     A probabilistic approach utilises real data, i.e., metered energy           1.3. Data for UBEM and clustering approaches
use or building statistics, to identify the building parameters with the
strongest correlation to the energy use intensity. Building archetype                The data that can be used for bottom-up, hybrid UBEM mainly re-
characteristics can be represented by probabilistic distributions instead        quires four types of data inputs: geometric data, non-geometric data
of ﬁxed values. Statistical approaches are easy to implement and can             (including usage patterns and statistical data), weather data, and vali-
accurately predict the energy demand for a large building stock. How-            dation/calibration data [20].
ever, they have a high dependence on data availability and are poor                  The access to real/metered energy data for validation and calibra-
at noticing patterns in the building stock, as statistical models do not         tion is often restricted [20,21] resulting in most UBEM studies lacking
provide representation and disaggregation down to individual building            proper model validation [6]. In a comprehensive taxonomic review of
level [10].                                                                      UBEM workﬂows, Malhotra et al. [22] found that only 44% of studies
     Cluster analysis techniques instead start from noticed patterns, pro-       validate the outputs using measured data and 30% does not perform
viding an unsupervised classiﬁcation of the data according to their              any validation at all. Access to metered energy use values or other re-
similarities. Multivariate cluster analysis (MCA), or just clustering, is        stricted data makes the model better tailored for a speciﬁc location. This
a central and useful data-mining technique concerned with the iden-              aﬀects the modelling process’s ability to be reproducible or transferable
tiﬁcation of homogeneous groups within a data set [11]. With MCA                 to other locations. This is a common issue in UBEM, where the over-
techniques, many building features can be analysed in parallel and with          whelming majority of reviewed publications cannot be reproduced as
a more exact segmentation of the building stock compared to traditional          data sources and simulation models are not openly available, and that
classiﬁcation procedures [12]. They do not impose particular weights             the process is not described in detail [22]. Limiting the data sources

                                                                             2
L. Dahlström, F. Johari, T. Broström et al.                                                                                    Energy & Buildings 303 (2024) 113823


to public data sets and records makes the model less speciﬁc and less              there are still many buildings currently in use that are missing in the
sensitive to characteristics of given data. One major advantage is then            EPC data set. For buildings that do have EPCs, archetypes are needed
the ability to apply the model for any location, since the data should             for characterisation of properties that are not in the EPCs but are re-
be equally available and accurate for the whole country (if using public           quired for energy simulation of the buildings, such as the construction
national data sets).                                                               of building elements, materials used, etc. The basic idea behind the ap-
    For buildings within the EU, there are openly available databases for          proach of this study is the assumption that buildings that are grouped
archetype or reference buildings and energy-related indicators, such as            together by similarity in certain respects, e.g. by the method proposed
TABULA [23] and ODYSSEE [24]. However, they are deterministically                  in this paper, will also be similar in these other respects, so that the
deﬁned and contain data on a national level, which disregards impor-               missing properties can be identiﬁed from the archetype buildings.
tant information regarding local building stocks. Reliance on determin-
istic assumptions simpliﬁes parameters that are particularly relevant in           1.4. Aim, research gaps and contributions
energy modelling and assumptions considered for national level build-
ing stocks may not hold true for district level archetypes, which can                  The use of clustering methods for building archetype development
lead to results that misrepresent urban energy demands [25].                       in UBEM is an emerging ﬁeld of research. A core task is to improve
    In a review of common UBEM applications, evaluating research gaps              model quality and accuracy while still ensuring low computational cost
and examining auxiliary model inputs, Dahlström et al. [7] found sev-              and low data collection diﬃculty. Determining the optimal number of
eral areas for further potential developments in UBEM, especially for              clusters is also crucial when using clustering methods, especially k-
building archetype classiﬁcation. Among them are advances in data                  means. Recognised and advanced methods to do this exists, but a simple
gathering from comprehensive databases such as the EPC database, and               and cost-eﬀective yet precise method would be preferable. The overall
increasing the number of classiﬁcation parameters, especially through              procedure needs to be simple and reliable, which can be achieved by
clustering processes. It was also found that including socio-economic              expanding on simple methods and by detailed evaluation for reliable re-
parameters, such as household income and demographics, is commonly                 sults. There is also a lack of exploration of clustering parameters; many
mentioned as a possible improvement for UBEM, but is mostly absent                 parameters have not been tested in clustering analysis for archetype de-
in the literature.                                                                 velopment applications, including socio-economic parameters. As the
    Energy Performance Certiﬁcates (EPCs) are public domain docu-                  problem of acquiring metered energy use data or real building charac-
ments allowing energy use comparison in the building stock and iden-               teristics for archetype development and/or validation is still a barrier
tiﬁcation of possible energy eﬃciency improvements [26]. In most EU                for UBEM studies, accurate models that can run on only open data sets
countries, energy performance assessments are based on calculations                are desired.
derived from building parameters and statistical data, along with some                 This paper aims to bridge these knowledge gaps by proposing a
measured values. A notable exception is Sweden, where most collected               new simple clustering methodology for developing building archetypes
EPCs are assessed using measured values [27,28]. The main focus of                 for hybrid UBEM, using open data sets and multiple diverse variables,
the Swedish EPCs is to provide data on building energy use for heat-               speciﬁcally including socio-economic parameters. The process should
ing, cooling and tap water, and to provide proposals for possible energy           be reliable and possible to validate without the use of metered en-
eﬃciency measures [29]. The energy use is presented as measured val-               ergy use or real building data. With an easily adaptable and eﬃcient
ues per energy carrier, total energy performance (as kWh/m2 ), as well             modelling methodology, using only open data, the procedure could be
as building energy class (based on primary energy conversion factors).             widely applied by decision-makers, researchers or other stakeholders to
Additionally, the EPCs contain data on building use type, construc-                create reliable and accurate UBEMs with considerable less time and ef-
tion year, total heated area, address and location, ventilation system             fort. Building footprint geodata and EPC data are available for the coun-
installed, electricity production (i.e. solar panels) and corresponding            tries of the EU and the UK [34,35], and statistics for socio-economic
metadata.                                                                          indicators exist but is likely varied in extent and presentation between
    The interest for EPCs is currently growing in governing bodies, most           each country. This should enable the methodology to be utilised for
notably in the EU. A recent proposal to the European Commission calls              most European building stocks. The novelties and main contributions
for the EPCs to be updated by 2025 [30], and to ensure comparability               of this paper are as follows:
across the EU, all EPCs shall be based on a harmonised scale of (new)                  First, we extend the use of k-means and the so-called elbow method
energy performance classes and comply with a common template. Ad-                  for identifying the optimal number of clusters. In particular, we present
ditionally, the proposal aims to increase the EPC coverage across the              the novel use of cluster “distinctness” and the use of a divergence point
Union. Each member state shall set up a national database, and the                 for analysing the maximum number of stable clusters. Secondly, we ap-
obligation to have an EPC is extended to all public buildings, buildings           ply clustering simultaneously to building geometric parameters, heating
with renewed rental contracts and buildings undergoing major renova-               systems and socio-economic factors, which has not been done previ-
tion [30].                                                                         ously in the available literature. Thirdly, as shown in the review paper
    Consequently, EPC databases are one of the most extensive data                 by Malhotra et al. [22], 95% of UBEM studies cannot be reproduced,
sources for building energy performance currently available, especially            which is a major issue for the ﬁeld. This work utilises open data sets and
in the countries of the EU and in the UK [31]. EPCs are often issued by            various data-matching techniques to get around this problem, paving
governmental agencies and are mandatory if certain criteria are met.               the way for later UBEMs that are accurate yet fully reproducible. It
As a result, EPCs are rapidly growing as a tool for decision-makers and            should be noted that the proposed method is limited to the ﬁrst impor-
energy modelling researchers among others [8,32,33].                               tant step in archetype-based UBEM, the identiﬁcation of representative
    There has been some criticism regarding data quality and content               archetype buildings. This is done from data that are openly available
[8] as well as of the accuracy of the methods for deriving the heated              for all buildings. Further steps in the modelling process, such as de-
ﬂoor area [28] but the database is continuously updated, and the un-               tailed characterisation of the representative archetype building (which
certainties have recently been reviewed and assessed by von Platten                requires collecting detailed building information for the chosen repre-
et al. [31]. In Sweden, EPCs are mandatory since 2006 for newly con-               sentative building) and modelling and simulation of buildings based
structed buildings, if the building is larger than 250 m2 or if the building       on the archetypes (which requires a validated UBEM), are outside of
is made available for sale [26]. The EPC coverage, measured in EPCs                the scope of this paper. Therefore, the main result of the paper is
per capita, varies from country to country and is currently highest in             the proposed clustering-based method and not the resulting archetypes
the UK, Ireland, and Denmark, where Sweden is also in the top cate-                themselves, nor application of them in UBEM simulations. The empha-
gory [34]. Although this coverage is increasing, the issue remains that            sis of the paper is on the methodology, while analysis, description and

                                                                               3
L. Dahlström, F. Johari, T. Broström et al.                                                                                      Energy & Buildings 303 (2024) 113823




                             Fig. 1. Overview of the UBEM work ﬂow with the Building Data and Archetype Development sections highlighted.


characterisation of the resulting archetypes are covered more brieﬂy
and mainly left to future studies where the archetypes are applied in
UBEM.

1.5. Structure of the paper

    In this paper, representative building archetypes are identiﬁed using
a multi-parameter clustering approach. The k-means clustering algo-
rithm is applied over a large data set including data retrieved from
several open-data sources. Two case study areas are used for the study,
with highly diﬀerent building stocks. The two cases are used to deter-
mine the accuracy of the procedure, but also to test the eﬀectiveness
of applying the methodology for a new building stock. In this work,
all stages of the identiﬁcation and clustering process are considered.
First, the clustering parameters are chosen based upon a literature re-
view. Building data are collected from several open-data sources and
are subject to relevant pre-processing, before all buildings are assigned
parameter values by combining these data sets and using spatial inter-
polation of aggregated data. After deciding upon which cluster analysis
algorithm to apply, the problem of determining the optimal number
                                                                                                     Fig. 2. Overview of the research methodology.
of clusters is addressed, which directly inﬂuences the resulting number
of building archetypes when using a clustering approach. Finally, the
accuracy of the methodology is evaluated using the appropriate error                  later presented in Section 2.5. How to determine the optimal number
metrics, and introducing a novel metric for analysing how representa-                 of clusters for the algorithm is described in Section 2.6. The evaluation
tive the identiﬁed clusters are.                                                      and validation of the clustering results, using diﬀerent metrics and in-
    The remainder of this paper is structured as follows. Section 2                   dices, is included in Section 2.7. A general UBEM framework and work
presents the data used in this study, describes the sources and associated            ﬂow is presented as a ﬂowchart in Fig. 1, with the sections covered by
pre-processing steps, and subsequently describes the study methodol-                  this study highlighted with weighted and dashed outlines. A schematic
ogy clustering procedure. The results and analysis of the results and                 overview of the research methodology and work ﬂow of this study is
the identiﬁed archetypes are presented in Section 3. Section 4 provides               shown in Fig. 2.
a discussion of the ﬁndings, followed by a wrap-up and conclusion in                      The method is based on using data that are openly available for each
Section 5.                                                                            building and applying the proposed extended k-means clustering anal-
                                                                                      ysis to identify clusters of buildings that have similar properties, and
2. Methodology and data                                                               within each cluster ﬁnd one archetype building that is representative
                                                                                      of the cluster. The basic premise or assumption is that if the archetype
   This section describes the procedure for cluster analysis used in this             is representative of the cluster in terms of the analysed parameters,
paper, including data, case studies and clustering methodology.                       then it will also be representative in terms of other characteristics (con-
   Section 2.1 introduces the case studies and data sources used in this              struction details, U-values, etc.) that are not available for all buildings
study. The parameters later included in the clustering process, and how               but still needed in order to fully characterise, model and simulate the
they were processed, are presented in Section 2.2. How the parameters                 buildings within an UBEM. Thus, instead of having to characterise each
were included in the clustering algorithm, by assigning them to build-                individual building in detail, this has to be done only for the identiﬁed
ings, is explained in Section 2.3. Section 2.4 describes the subsequent               archetype buildings. As Fig. 2 shows, the process analysed in this paper
data cleaning procedures. The clustering algorithm and how it works is                is limited to the clustering and archetype identiﬁcation, whereas fur-

                                                                                  4
L. Dahlström, F. Johari, T. Broström et al.                                                                                       Energy & Buildings 303 (2024) 113823


                                                                                                     Table 1
                                                                                                     Number of buildings in the EPC data set.

                                                                                                       Category   EPC, Uppsala         EPC, Gotland

                                                                                                       SFH        3723                 2861
                                                                                                       MFH        3319                 1237
                                                                                                       Industry   141                  17
                                                                                                       Misc.      923                  929



                                                                                                            Table 2
                                                                                                            Grouping for resident age
                                                                                                            based on statistical data.

                                                                                                              Group      Resident age span

                                                                                                              1          0-6 years
                                                                                                              2          7-15 years
                                                                                                              3          16-19 years
                                                                                                              4          20-24 years
                                                                                                              5          25-44 years
                                                                                                              6          45-64 years
                                                                                                              7          65+ years



                                                                                     and schools. The total number of residential buildings is 7042 for the
                                                                                     Uppsala data set, and 4098 for Gotland.
                                                                                         Cadastral data, or geographic information system (GIS) data, were
                                                                                     obtained from the Swedish Mapping, Cadastral and Land Registration
                                                                                     Authority [36] for properties and buildings. The GIS dataset is assumed
                                                                                     to include all known buildings present at the time for data collection.
                                                                                     The relevant cadastral data obtained includes building and property
                                                                                     footprints and coordinates, with corresponding property address and
                                                                                     building type. The division by typology is done in a similar but not
Fig. 3. Geographical location of 1. Uppsala and 2. Gotland within Scandinavia.       exact same way as for the EPC dataset, which makes comparison by
                                                                                     building type between the two data sets diﬃcult. A high percentage of
ther characterisation, modelling and simulation will be approached in                MFH and misc. buildings have EPCs, while the EPC coverage of SFH
future research.                                                                     is low. This is especially true for Gotland, due to the large numbers of
                                                                                     SFH in a rural context, including summer houses, small farmsteads etc.
2.1. Case studies and data sources                                                   which are not required by law to have an EPC [26].
                                                                                         For statistical data, factors such as income, education, home own-
    For this paper, two case studies were chosen to be able to compare               ership and sometimes also gender, ethnic background or similar can
the results of the analysis and to analyse the relative diﬃculty of us-              collectively be referred to as socio-economic data or indicators. In Swe-
ing the procedure for a completely new data set. The ﬁrst area is the                den, socio-economic and statistical data are available from the national
city of Uppsala, Sweden, and the second area is the island of Gotland,               agency Statistics Sweden (SCB) [37]. Data that can be acquired for a
Sweden’s largest island. The island of Gotland is mostly rural, with one             geographic area include resident age, gender, marital status, education,
city and some smaller towns and villages. Rural areas are not generally              employment, income and total population. The data are aggregated ge-
included in UBEMs and including areas greater than just urban areas                  ographically and anonymised in the database, so as to be considered
is not discussed in literature. The main diﬀerence usually stated is the             open and non-sensitive. Resident age is assigned in this data set ordered
diversity of the building stock, and the Urban Heat Island eﬀect [6],                by age group, as described by Table 2. For cadastral and statistical data,
which creates a diﬀerent micro-climate in urban areas compared to ru-                no area division based on similar borders was available. For simplicity,
ral. Being an island, the Gotland area has a deﬁned system boundary,                 all data within a coordinate rectangle that enclose all buildings in the
creating the opportunity to include all buildings and gather data for the            EPC data set was included (See Fig. 8).
whole region. For a city like Uppsala, the area to include in the model
is inherently more arbitrary; the included area for data acquisition can             2.2. Clustering parameters
be deﬁned either by pre-made deﬁnitions, like postal areas, or manu-
ally by drawing a (subjective) boundary. The included case study areas               2.2.1. Building characteristics
and their respective geographical location within Scandinavia is shown                   The EPCs contain information about building construction year,
in Fig. 3.                                                                           heated area (building area heated to > 10 ◦ C), energy use (for heat-
    All buildings with a postal code that matched the case study area                ing and electricity) and energy performance (kWh/m2 ), all of which
in the EPC data set were included in the study. The focus in this pa-                can be used as parameters for cluster analysis. For building energy use,
per is on residential buildings due to insuﬃcient sample size in the EPC             the EPCs account for the amount of energy used for heating in kWh/yr.
database (industry buildings are not required by law to have an EPC                  Nearly all values are metered or calculated from annual fuel consump-
in Sweden [26]) and higher complexity for non-residential or indus-                  tion, which is then standard year-corrected to better represent the long-
try buildings. Residential buildings are often further divided into single           term characteristics of the building. With standard year-correction, the
family housing (SFH) and multifamily housing (MFH) because of their                  normal climate in the locality of measurements is compared to how
inherent considerable diﬀerences, a convenient categorisation that is                the climate has been during the particular period for which there are
also used in this paper. The number of included buildings divided by                 measured values, and corrected using an Energy Index issued by the
building type is presented in Table 1, where miscellaneous buildings in-             national weather authority [38]. The national weather authority in Swe-
clude mixed-use and non-residential buildings, for example restaurants               den, SMHI, has recently updated the standard year period by moving it

                                                                                 5
L. Dahlström, F. Johari, T. Broström et al.                                                                                   Energy & Buildings 303 (2024) 113823


                   Table 3                                                         2.2.2. Statistical data
                   Building heating systems.                                           Socio-economic factors such as resident income, gender and age (see
                     Heating system           Included heating systems             Section 2.1) have been proven to aﬀect domestic electricity consump-
                     main group               and sources                          tion [41,42], energy demand for heating [43,44], per capita electricity
                     District heating         District heating                     consumption [45,46] and building energy performance [47]. Total pop-
                                              District cooling                     ulation can also be converted into population density, which has a
                                                                                   negative correlation with CO2 -emissions [2] and energy use [48] per
                     Boilers                  Oil
                                              Gas                                  capita. This eﬀect however also relates to resident income; in dense
                                              Firewood                             wealthy areas, in for example the USA, population density instead has
                                              Wood chips/pellets                   a positive correlation with CO2 -emissions [2]. Socio-economic factors
                                              Misc. biofuels                       are directly tied to building occupant presence and behaviour, which in
                     Electric heating         Water-based electric heating         turn largely inﬂuence the energy demand of buildings [7,49]. The insuf-
                                              Direct electric heating              ﬁcient use of occupant behaviour models is one of the major causes of
                                              Forced air electric heating          the “performance gap” in UBEM, i.e. the diﬀerence between simulated
                                              Comfort cooling
                                              Building electricity
                                                                                   and observed energy use [49].
                                                                                       Statistical and socio-economic data are publicly available as aggre-
                     Heat pumps               Ground-source heat pump              gated data. Detailed and building-speciﬁc data would be more useful
                                              Air-source heat pump
                                              Water-source heat pump
                                                                                   and provide more accurate results; however, aggregated data is neces-
                                              Exhaust air heat pump                sary to use since the GDPR European Union law [50] applies to personal
                                                                                   data, i.e., information that is related to an identiﬁed or identiﬁable indi-
                                                                                   vidual. For acquiring personal data in Sweden, an ethics review process
forward 10 years. This will cause diﬀerences from previous EPC energy              is necessary, which is resource- and time-consuming and the obtained
values as the mean temperature has increased by 0.5 ◦ C during this pe-            data would not be considered open-source. Also taking into account
riod [39]. For energy performance the corrected values for heating are             the diﬃculty of acquiring metered energy use data, designing an UBEM
divided by the heated area. The energy use values are reported for each            framework consisting of only publicly available data sets is a more com-
type of heating system, which were divided as shown in Table 3. Using              pelling and practical approach.
EPC data, the buildings can be categorised after which heating systems                 Resident gender was included as one of the socio-economic building
they use; however, as many buildings do not exclusively use one source             parameters obtained for cluster analysis. However, the data proved to
of heating but rather a mix of several, it is of no use to deterministically       be the most homogeneous of the parameters, with most values being
categorise the buildings after heating system. One solution is instead             within a close distance to the mean. If the majority of clusters have
to calculate the share of each heating system used for each building.              a mean value for the share of gender that is close to the mean of the
Heating of hot water is included but assumed to be heated by the same              whole data set, the division into clusters for this parameter becomes
share of heating systems. An example for a rural SFH could then be 0%              redundant. Therefore, it was decided to not use resident gender as a
district heating, 50% boilers, 10% electric, and 40% heat pump.                    parameter for the ﬁnal results of the study.
    Building volume, often simpliﬁed as building footprint area multi-
plied by the height, is often used as a model parameter. In a study                2.3. Assigning data to buildings
using multivariate cluster analysis for UBEM using archetype buildings,
Ghiassi and Mahdavi [11] show that including building size as a clas-                 The selected parameters were:
siﬁcation criterion relatively increased predictive performance when
comparing otherwise similar scenarios. To estimate the height of build-             1. Construction year
ings, in most existing UBEMs, the 3D representation of the building                 2. Building volume [m3 ]
morphology, referred to as 3D city models, is the most reliable source              3. Energy performance [kWh/m2 ,yr]
of information. Yet, in the absence of these comprehensive 3D city mod-             4. Income per person [kSEK]
els generated, simpler versions of these types of models have to be                 5. Resident age (group, mean value)
made from scratch. The common method for making 2.5D or simpli-                     6. Population density [ppl/km2 ]
ﬁed 3D models of buildings is to make use of LiDAR point clouds to                  7. Share of district heating
approximate the elevation of buildings from the ground and extrude                  8. Share of boilers
the building footprints accordingly. In this study, using an open-source            9. Share of electric heating
tool, 3dﬁer [40], and available data on building footprints, and LiDAR             10. Share of heat pumps
point clouds, 3D shoebox models of building stocks in Sweden were
created. The available national LiDAR data in Sweden is considered as                  Connecting EPC data to GIS data requires some ﬁne-tuning. The
low-resolution where the point density is only 0.5-1 point/m2 . There-             EPCs do not include geographic coordinates and the GIS data does not
fore, for some of the buildings, especially those partly or completely             include building postal addresses. Another issue is that the GIS data set
over shadowed by another object, such as a tree, the actual height of              contains all buildings known, up to the date of data retrieval, but the
the building cannot be properly captured from the low resolution point             EPCs cover only a percentage of the existing building stock (see Sec-
clouds. This issue can be occasionally seen in single-family buildings.            tion 2.1), which creates a discrepancy in data coverage. Our solution
Therefore, a post-processing method for altering the estimated height              was to make EPCs the ﬁrst priority data set, and assign other values
from low-resolution data was used. In this multi-step method, the esti-            based on the EPCs. One way to easily connect the two data sets is by
mated height is ﬁrst compared to the average height of similar building            property address, since the property address is present in both data sets.
types in the surrounding area. If the error is bigger than the chosen              One property can contain multiple buildings but a majority of proper-
threshold of 30%, then the height is recalculated based on the aver-               ties (90% in Gotland and 84% in Uppsala) have only one issued EPC.
age height as well as the available information on the number of ﬂoors,            In the case of multiple EPCs on the same property, most are observed
heated ﬂoor area and the footprint area of a building. The choice of               to be similar buildings with duplicate or highly similar EPCs, represent-
30% as a reasonable error threshold was chosen as a trade-oﬀ between               ing row/terraced houses or arrays of similar MFH. The cadastral data is
calculation complexity and accuracy.                                               assigned to the EPC with the corresponding property address. This ap-

                                                                               6
L. Dahlström, F. Johari, T. Broström et al.                                                                                Energy & Buildings 303 (2024) 113823


proach introduces some uncertainties, but is assumed to still create a           and is often preferable to standardisation, such as Z score methods, for
useful estimate of building parameter values across the building stock.          k-means clustering parameters [53].
    The socio-economic and statistical data is available in coordinate
squares, 250×250 m in size, aggregated so that the values for the square         2.5. Clustering algorithm
are the total and mean of all residents with a registered address that
are within the boundaries of the square. Given the coordinates of the                Based on the literature review (Section 1.2), k-means is selected as
square, it was possible to connect to the other data sets through the            the clustering technique for the building stock segmentation process in
GIS coordinates. However, since the data are aggregated it had to be             this paper.
distributed on the buildings in the evaluated data set, which then could             The k-means clustering method is a widely used technique, where
be done through spatial interpolation. From these values, a coordinate           the goal is to choose 𝑘 cluster centres in order to minimise 𝜙, the total
point grid was created, and the values belonging to each square were             squared distance between each point and its closest centre [54]. Ide-
assigned to the centre point of the square. From this grid, values were          ally, the algorithm should result in clusters whose members are close to
interpolated to form a ﬁner grid that was used to assign values more             each other (or have a high degree of similarity) and are well separated.
accurately for any point that is located between the original square grid        The technique divides 𝑛 observations into 𝑘 non-overlapping clusters,
points, i.e., all buildings with assigned coordinates.                           where 𝑘 centres 𝑐 are chosen to minimise the total squared distance,
    Before any interpolation process, outliers need to be removed. If            represented by the criterion function 𝜙:
some values are disproportionately large, this will aﬀect the neigh-                       𝑘 ∑
                                                                                           ∑
bouring values signiﬁcantly. For a normal distribution, the well-known           𝜙 = min             ||𝑥 − 𝑐𝑖 ||2 ,                                        (2)
                                                                                     𝑐∈𝐶
Empirical Rule or 3𝜎 -rule can be used to determine a reasonable con-                      𝑖=1 𝑥∈𝑋
ﬁdence interval or to identify outliers [51]. However, the evaluated             where 𝑥 represents a data point within the set 𝑋 ⊂ ℝ, 𝑐𝑖 is the centre of
parameters are not normally distributed and contain some exception-              cluster 𝑖, and 𝐶 is the set of cluster centres [13,55].
ally remote outliers (up to 25𝜎 ), so for this study outliers are removed           The k-means algorithm works as follows:
if they are outside 5 standard deviations (or 5𝜎 ) from the mean. Ac-
cording to Chebyshev’s Theorem, at least 96% of values will be found              1. Use the k-means++ algorithm for cluster centre initialisation (de-
within 5𝜎 for any distribution [52].                                                 scribed in detail by David and Vassilvitskii [54]).
    The grid size for the spatial interpolation was 50 meters. The grid           2. Compute the point-to-cluster-centroid distance of all observations
size is a variable that will be a compromise between accuracy and com-               with the squared Euclidean distance metric.
putational time; a smaller grid size would give more accuracy when                3. Assign each observation to the cluster with the closest centroid,
assigning values to the buildings, but at a higher computational cost.               or individually reassign observations to a diﬀerent centroid if the
    The socio-economic parameter values were later assigned to all                   reassignment decreases the total sum of distances.
buildings in the data set. The coordinates of each building were as-              4. Compute the average of the observations in each cluster to obtain
sumed to be its centre (calculated centroid of the building’s geometric              𝑘 new centroid locations.
shape). Each building was then assigned the parameter values in the in-           5. Iterate steps 2-4 until cluster assignments do not change (or a max-
terpolated layers that are nearest (Euclidian distance) to the building              imum number of iterations is reached).
centre coordinates.
                                                                                     The k-means++ algorithm selects an observation uniformly at ran-
2.4. Data cleaning                                                               dom from data set 𝑋 , which means that the cluster centres are ini-
                                                                                 tialised diﬀerently which each run. Ideally, the ﬁnalised clusters will be
2.4.1. Outliers                                                                  identical regardless of centroid seed and with identical total sum of dis-
    Outliers were treated in a similar way as for the statistical values         tances. Usually, however, with less deﬁned clusters or if the clustering
(see Section 2.3), where entries with parameter values ±5𝜎 from the              algorithm does not converge, the ﬁnalised clusters will diﬀer depend-
mean were removed for all clustering parameters except age group and             ing on centroid initialisation. To minimise that risk, the algorithm has
share of heating systems.                                                        an assigned number of replicates 𝑟 > 0 where 𝑟 diﬀerent sets of seeds
    To remove outliers for the construction year may seem uncalled for,          are selected. The clustering algorithm then proceeds with the replicate
but the process eliminates faulty entries if present and is useful for the       that resulted in the lowest local minimum, i.e. the lowest total sum of
Gotland building stock, as some buildings are exceptionally old (built           distances.
in the 12th century), which may unnecessarily skew the clusters and                  The algorithm was implemented in the MATLAB environment, build-
means.                                                                           ing upon the available kmeans function [56].

                                                                                 2.6. Determination of the optimal number of clusters
2.4.2. Normalisation
     The k-means algorithm is highly dependent on Euclidian distance,
                                                                                     Determining the optimal number of clusters, the value of 𝑘, is one
so the outcome of the method is sensitive to the magnitude of the
                                                                                 of the most common issues using the k-means method. This is agreed
clustering parameters, as larger numerical values will overshadow char-
                                                                                 upon in the reviewed literature, and a comparison with other UBEM
acteristics with smaller numerical values [11]. The order of magnitude           approaches not using cluster analysis in current research gives no fur-
will be diﬀerent for all clustering parameters, thus they need to be stan-       ther insights, as the number of archetypes can vary greatly, from 3 [57]
dardised or normalised to be comparable in the same range. This will             to 99 [58]. The basic idea when solving the issue is to run the algo-
prevent any unintended skewing of the results and guarantees that no             rithm for a range of k values, and evaluate a cluster quality index for
speciﬁc feature is given any particular weight to the disadvantage of            each run. A larger number of clusters (and associated representative
another [14].                                                                    buildings) may guarantee a higher accuracy and representation of the
     Feature scaling, or min-max normalisation, is a method used when            building stock, but with increased computational time, eﬀort, and re-
non-normally distributed data needs to be scaled to a ﬁxed range, or to          sources required for model creation [14].
allow operations to be performed on all points at the same scale [14].
It is deﬁned as:                                                                 2.6.1. Elbow method
         𝑋 − 𝑋𝑚𝑖𝑛                                                                   One of the ﬁrst methods, and most used, is the elbow method [59].
𝑋𝑛𝑜𝑟𝑚 =                                                               (1)        The method involves plotting an error metric against the number of
        𝑋𝑚𝑎𝑥 − 𝑋𝑚𝑖𝑛

                                                                             7
L. Dahlström, F. Johari, T. Broström et al.                                                                                         Energy & Buildings 303 (2024) 113823


clusters, and utilising the resulting graph to determine the optimal value         all characteristics equal to the cluster centroid, which is deﬁned as the
of clusters. The goal is to have the error value as low as possible (for           hypothetical mean value for each parameter in each cluster. When using
as few clusters as possible), as it indicates more homogeneous clusters.           sample buildings, the archetype is the existing building that is closest
However, when the number of clusters 𝑘 increases, the error value gen-             for all parameters to the average building [18]. In this paper, the term
erally decreases. When there are as many clusters as there are data                archetype refers to sample buildings. To ﬁnd archetype buildings for
points in the analysed dataset, it will be equal to zero. An inﬂection             each cluster, the sample building can be deﬁned by ﬁnding the EPC
point (“elbow” or “knee”) in the graph thus indicates the number of                building with the shortest total distance for all parameters to the cluster
clusters where increasing the value of 𝑘 will not improve the results              centroid. This is found by calculating the Euclidean distance between
signiﬁcantly, implying that the value of 𝑘 at the inﬂection point is the           the centroid and all the EPCs in the cluster, using a nearest point-search
optimal number of clusters.                                                        algorithm [67].
    Criticism against the method has stated that it is too simple, and                 The representativeness index can be used to evaluate the level of sim-
that there is a signiﬁcant risk of not being able to determine the op-             ilarity between the virtual and the actual archetype building [19]. If
timal value of 𝑘 because the resulting error curve is not always clear             the closest EPC has the exact same characteristics for each parameter as
[59,60]. The elbow method has since largely been substituted for dif-              the cluster centroid, the representativeness would be 100%. The metric
ferent approaches, including silhouette analysis [61], optimising cer-             is deﬁned so that only fairly high values (>95%) indicate a represen-
tain information criteria [62], and the gap statistic [63]. Some studies           tative cluster; for Gangolells et al. [19] the values ranged from 76.%
have used the R package NbClust [64] which proposes the best clus-                 to 100%. As the mean values (and spread) of the building parameters
tering scheme by providing 30 indices for determining and evaluating
                                                                                   are useful for visualisation and could be important for the next steps in
the number of clusters and by varying all combinations of number of
                                                                                   UBEM, the representativeness could be a useful way of determining the
clusters, distance metrics, and clustering methods (including k-means).
                                                                                   stability of the clustering results. The representativeness is also diﬀer-
The method, however, has a high computational cost, and for Borges
                                                                                   ent for each cluster, which makes the metric a useful tool for comparing
et al. [17] it resulted in only 2 clusters for each segmentation, and for
                                                                                   resulting clusters with each other.
Ghiassi and Mahdavi [11] the majority of scenarios had 6 clusters, a
                                                                                       The representativeness for each parameter can be expressed as
lowest-limit number deterministically deﬁned beforehand in order not
to have too few clusters; this indicates that the NbClust method tends                     ∑𝑑
towards low number results.                                                                   𝑗=1 𝑤𝑗 (1 − |𝑝𝑗,𝑐𝑒𝑛𝑡 − 𝑝𝑗,𝑎𝑟𝑐ℎ |)
                                                                                   𝑅𝑗 =                ∑𝑑                       ,                                   (6)
                                                                                                          𝑗=1 𝑤𝑗
    For the elbow method, a variety of error metrics can be used to ﬁnd
the elbow to ascertain the value of 𝑘. Therefore, if the method can be
                                                                                   where 𝑝𝑗,𝑐𝑒𝑛𝑡 is the parameter value for the cluster centroid, 𝑝𝑗,𝑎𝑟𝑐ℎ is
extended with new approaches, it could therefore still prove a valuable
tool for cluster analysis.                                                         the parameter value for the actual archetype building, and 𝑤 denotes
                                                                                   the weighting coeﬃcient [19]. Without weighting coeﬃcient, we have
2.6.2. Error metric for the elbow method                                           a mean representativeness for each cluster that corresponds to
    Halkidi et al. [13] assess a wide variety of clustering validation tech-                  𝑑
niques and trends. One of the more promising evaluated validity indices                   1∑
                                                                                   𝑅𝑖 =         (1 − |𝑝𝑗,𝑐𝑒𝑛𝑡 − 𝑝𝑗,𝑎𝑟𝑐ℎ |),                                         (7)
is the root-mean-square standard deviation (RMSSTD). Using the elbow                      𝑑 𝑗=1
method and the RMSSTD metric has been successfully used to deter-
mine the number of clusters for archetype building development [19],               which then can be multiplied by 100 to be presented as a percentage.
to cluster buildings for the optimisation design of integrated energy
systems [65] and for building energy benchmarking [66]. The metric is              2.7.2. Cluster spread
deﬁned as                                                                             The standard deviation was calculated for each parameter in each
                    ∑ 𝑘 ∑𝑑            ∑𝑛𝑖𝑗       1                                 cluster, where 𝜎𝑝,𝑗 is the standard deviation for a variable vector 𝑝 with
          ⎡                         (𝑥𝑞 − 𝑥̄𝑗 )2 ⎤ 2                               𝑁 scalar observations for each parameter 𝑗 , deﬁned as
                       𝑖=1      𝑗=1     𝑞=1
𝑅𝑀𝑆𝑆𝑇 𝐷 = ⎢              ∑𝑘 ∑𝑑
                                                 ⎥ ,                    (3)
          ⎢                                      ⎥                                         √
          ⎣               𝑖=1 𝑗=1 (𝑛𝑖𝑗 − 1)      ⎦                                         √
                                                                                           √      1 ∑
                                                                                                       𝑁
where 𝑘 is the total number of clusters, 𝑑 is the total number of parame-          𝜎𝑝,𝑗   =√             |𝑝 − 𝜇|2 ,                                                 (8)
                                                                                                𝑁 − 1 𝑛=1 𝑛
ters, 𝑥 is a data point, 𝑥̄𝑗 is the mean of data values of 𝑗 dimension, and
𝑛𝑖𝑗 is the number of data values of 𝑗 dimension that belong to cluster 𝑖.          where 𝜇 is the mean of 𝑝:
For all further calculations or descriptions in this paper, the 𝑖 dimension
indexes clusters, and the 𝑗 dimension indexes parameters.                                     𝑁
                                                                                          1 ∑
    In this case study the number of data points in each cluster is equal          𝜇=          𝑝 .                                                                  (9)
                     ∑𝑑                                                                   𝑁 𝑛=1 𝑛
for all parameters, 𝑗 𝑛𝑖𝑗 = 𝑑𝑛𝑖𝑗 , which gives
                                                                                       The magnitude of the standard deviation depends on the magnitude
𝑘 ∑
∑ 𝑑               𝑘
                  ∑                                                                of the parameter values, so the standard deviation is not comparable be-
    (𝑛𝑖𝑗 − 1) = 𝑑( 𝑛𝑖𝑗 − 1),                                            (4)
                                                                                   tween diﬀerent parameters (see Section 2.4). For the parameter spread
𝑖=1 𝑗=1                   𝑖=1
                                                                                   examined in this paper we are also interested in absolute spread, not
and thus                                                                           the diﬀerence from the mean, as we want to compare the magnitude
          √
          √ ∑𝑘 ∑𝑑 ∑𝑛𝑖𝑗                                                             of spread for each parameter and cluster. To be able to make a fair
          √
          √ 𝑖=1 𝑗=1 𝑘=1 (𝑥𝑘 − 𝑥̄𝑗 )2                                               comparison between all clustering parameters, the standard deviation
𝑅𝑀𝑆𝑆𝑇 𝐷 = √       ∑                  .                                  (5)
                𝑑( 𝑘𝑖 𝑛𝑖𝑗 − 1)                                                     is taken after normalisation of the parameters (with feature scaling, see
                                                                                   equation 1), so that it becomes an absolute value between 0 and 1. The
2.7. Evaluation of clustering results                                              mean value for all parameters in each cluster can then represent the
                                                                                   mean spread for each cluster, as
2.7.1. Identiﬁcation of cluster centroids and building archetypes                                 𝑑
   When applying cluster analysis, the archetype deﬁnition can diﬀer.                         1∑
                                                                                   𝑆𝑡𝑜𝑡,𝑖 =        𝜎 .                                                            (10)
When using average buildings, the archetype is a virtual building with                        𝑑 𝑗=1 𝑝,𝑗

                                                                               8
L. Dahlström, F. Johari, T. Broström et al.                                                                                   Energy & Buildings 303 (2024) 113823


2.7.3. Cluster distinctness
    A combination of the two previously discussed metrics may be used
to more accurately determine the optimal number of clusters, and more
importantly, visualise the diﬀerences between each 𝑘. For an ideal re-
sult, the representativeness should be as high as possible and the total
spread as low as possible. Since the goal with clustering is to divide
the entire set of data points (i.e., all buildings in the building stock),
it is not enough to have several clusters with desirable values, if one
or more clusters perform worse. As such, the representativeness and
spread should be acceptable over the full set of clusters. A combination
metric can be deﬁned to take both these measures into account, for an
easier evaluation and visualisation of the clustering results. This novel
metric we call the distinctness of each cluster.
    The distinctness of a cluster is deﬁned to give equal weight to both
representativeness and total spread for each cluster. Both the represen-
tativeness 𝑅 and the cluster spread 𝑆𝑡𝑜𝑡 are numbers between 0 and 1,
but it is desired for the clusters to have a high representativeness and
low spread. We can then deﬁne the distinctness 𝐷 for each cluster as

𝐷𝑖 = 𝑤𝑅𝑖 + (1 − 𝑤)(1 − 𝑆𝑡𝑜𝑡,𝑖 ),                                       (11)
where 𝑤 is a weighting factor, which is here set to 𝑤 = 0.5 to give
equal weight to both indices. If 𝑤 = 1, the distinctness equals the rep-
resentativeness, and if 𝑤 = 0 it equals the cluster spread. Regardless,
𝐷 is also ranging from 0 to 1, where 1 is the highest possible distinct-
ness, i.e., a perfect cluster of 100% representativeness and no cluster
spread. To analyse the distinctness for each number of 𝑘, so as to de-
termine the optimal number of 𝑘, the distinctness has to be determined
for all clusters simultaneously in each subsequent run. For this purpose
the median value of the distinctness is used, as the distribution is likely
to be skewed or have outliers present.

3. Results and analysis

    This section presents the results of the clustering procedure and
archetype development, and analyses the ﬁndings. The discovery of it-
eration instability in the clustering algorithm is described in Section 3.1.
The determined optimal number of clusters and the results of using the
new evaluation metrics are presented and analysed in Section 3.2. Sec-                  Fig. 4. RMSSTD (a) and median distinctness (b) for SFH in Uppsala.
tion 3.3 later presents the identiﬁed archetypes and relates them to the
real building stock.
                                                                                   practice buildings are assigned to certain clusters simply because they
3.1. Clustering iteration instability                                              have to be assigned somewhere, and not because it improves the qual-
                                                                                   ity indices. This “forced” assigning could be somewhat arbitrary, and
    The k-means clustering process uses replicates to ﬁnd and proceed              is likely dependent on the initial conditions, since the ﬁrst step in the
with the replicate resulting in the lowest total sum of distances (see             algorithm is based on a randomised seeding technique (see Section 2.5).
Section 2.5). Even with a high number of replicates, diﬀerences in the                 For each subsequent cluster analysis, the number of replicates per
results could be noted for re-runs even when the process was expected              run was set high enough (𝑟 = 100) to ascertain that the diﬀerences in
to yield a similar result.                                                         the results are due to this inherent uncertainty of the process, and not
    The cluster analysis was run a number of times for an equal set-up of          that the algorithm itself did not converge.
clustering parameters. The resulting error metric values were then plot-
ted together in a graph, where a clear pattern could be noticed, which is          3.2. Optimal number of clusters
seen for 10 subsequent runs in Figs. 4–7. Both metrics display an equal
result for each number of clusters, up to a certain point, where the re-               To determine the optimal number of clusters using the elbow
sults start to diverge. Increasing the number of k also seems to amplify           method and RMSSTD, the goal is to ﬁnd the inﬂection point in the
the diﬀerence between each run. A diﬀerence in these metrics is an in-             graph. (see Section 2.6) For this analysis, k-means clustering was run
dicator of a diﬀerence in the ﬁnalised clusters. A minor diﬀerence in              on each dataset for 𝑘 = 1 to 𝑘 = 15 and the corresponding RMSSTD
the metric value is the eﬀect of that a few buildings change which clus-           value was computed and plotted.
ter they belong to between runs, and a large diﬀerence means that the                  Fig. 4 shows the RMSSTD and median distinctness values for each
ﬁnalised clusters are exceedingly dissimilar between runs. These results           value of 𝑘, for SFH in Uppsala. Each line/colour represent one run of
can be interpreted to show that increasing the number of clusters is no            the algorithm, and the graph shows 10 subsequent runs. In Fig. 4a it
longer useful after the divergence point, after which the clustering pro-          can be seen that the inﬂection point is clearly at 𝑘 = 7 for the RMSSTD,
cess becomes unstable. The algorithm will always assign an observation             which also seems to be the point where the values between each itera-
to the nearest centroid, meaning that the data point (building) would              tion start to diverge. The distinctness (Fig. 4b) shows a spike at 𝑘 = 2,
ultimately be assigned to the nearest cluster which leads to the most              and one again at 𝑘 = 7 before the iterations diverge also for this met-
improvement in reducing the criterion function 𝜙, even if the improve-             ric. The second spike at seven clusters also correlates with the clear
ment is very slight. This could lead to incorrectly deﬁned borders, so in          inﬂection point for the RMSSTD value. With 𝑘 = 2, only two archetypes

                                                                               9
L. Dahlström, F. Johari, T. Broström et al.                                                                                   Energy & Buildings 303 (2024) 113823




      Fig. 5. RMSSTD (a) and median distinctness (b) for MFH in Uppsala.                Fig. 6. RMSSTD (a) and median distinctness (b) for SFH on Gotland.



would represent the entire SFH building stock in Uppsala, which could              of choosing the number of clusters, as one metric may demonstrate a
be considered to be too few to be accurate enough, further indicating              clear result while the other does not.
that 𝑘 = 7 is the optimal value.
    Fig. 5 similarly shows the RMSSTD and median distinctness val-                 3.3. Identiﬁed clusters and building archetypes
ues for MFH in Uppsala. Here we have several inﬂection points for the
RMSSTD, at 𝑘 = 3, 𝑘 = 5 and 𝑘 = 9. The distinctness is also more vary-                 Table 4 shows the identiﬁed clusters for SFH and MFH in both
ing and showing several spikes, interestingly also at 𝑘 = 3, 𝑘 = 5 and             building stocks, with their corresponding clustering parameters. The
𝑘 = 9, before it diverges. Since the RMSSTD does not decrease much                 clusters are not ordered in any particular fashion. Uppsala then has 12
from 𝑘 = 5 to 𝑘 = 9, and the diﬀerence between each run increases,                 archetypes in total, 7 for SFH and 5 for MFH. Both types have one of
𝑘 = 5 can be argued to be the optimal number.                                      their largest clusters as the one with the highest distinctness and the
    Fig. 6 shows the RMSSTD and median distinctness for SFH in the                 smallest cluster with the lowest distinctness. The distinctness does not
Gotland building stock, and similarly for MFH in Fig. 7. Here the                  naturally correlate with cluster size, but if a city has a large number of
RMSSTD shows nearly no change over values of 𝑘 and has no inﬂec-                   very similar buildings, they would likely be assorted into the same clus-
tion point, until it diverges signiﬁcantly. The distinctness however has           ter, which would then have a lower spread. The smaller clusters could
a clear spike at 𝑘 = 7. For MFH we can instead see a sharp inﬂection               have a lower distinctness due to abundant buildings, or outlier build-
point at 𝑘 = 8 for the RMSSTD but here it is a dissimilar result for the           ings that, due to the cluster size, signiﬁcantly alter the indices.
distinctness, as the spike is at 𝑘 = 7. However, it is less deﬁned and the             Gotland has a smaller building stock but has a similar amount of
iterations start to diverge earlier, at 𝑘 = 6, and does so signiﬁcantly for        clusters (see Table 4) which could indicate a more diverse building
higher values of 𝑘. Six clusters are then argued to be optimal for MFH             stock, which is true in a sense, due to the amount of historic build-
as the distinctness is high and the drop in RMSSTD is not great enough             ings and that the Gotland building stock is both urban and rural (see
to justify the uncertainty the divergence induces. Increasing to 𝑘 = 7             Section 2.1). The total spread is signiﬁcantly higher for all SFH clusters
splits the largest cluster (archetype 6, see Table 4) into two with only           compared to Uppsala, which is due to higher diversity in the cluster-
slightly diﬀerent parameter values, but otherwise leaves the other ﬁve             ing parameters but it could also imply that the clustering algorithm is
practically identical. This also supports the argument that six clusters           not able to ﬁnd as homogeneous clusters. The patterns regarding clus-
are suﬃcient for this subset. The results for Gotland indicate that using          ter size and distinctness are not as apparent on Gotland even though the
these two metrics simultaneously can signiﬁcantly simplify the process             same conclusions can be drawn.

                                                                              10
L. Dahlström, F. Johari, T. Broström et al.                                                                                              Energy & Buildings 303 (2024) 113823


                            Table 4
                            Final clustering results for the resulting 𝑘 values, for SFH and MFH in Uppsala and Gotland.

                              Cluster number   Cluster size               Representativeness 𝑅𝑖 [%]   Cluster spread 𝑆𝑡𝑜𝑡,𝑖 [%]   Distinctness [%]
                                               [number of buildings]
                              Uppsala
                              SFH

                              1                819                        98.3                        13.7                        92.3
                              2                1091                       98.9                        10.6                        94.1
                              3                66                         95.9                        22.2                        86.8
                              4                546                        98.2                        15.9                        91.2
                              5                318                        97.3                        16.4                        90.5
                              6                463                        97.8                        15.0                        91.4
                              7                215                        97.9                        16.6                        90.2

                              MFH

                              1                1116                       98.8                        13.1                        92.8
                              2                704                        97.6                        12.9                        92.3
                              3                130                        95.4                        20.7                        87.3
                              4                337                        96.0                        18.1                        89.0
                              5                942                        98.5                        11.5                        93.5

                              Gotland
                              SFH

                              1                747                        97.7                        16.1                        90.8
                              2                292                        96.9                        18.8                        89.1
                              3                204                        95.9                        16.2                        89.9
                              4                390                        97.7                        16.0                        90.9
                              5                463                        97.8                        17.5                        90.1
                              6                242                        95.8                        18.1                        88.8
                              7                412                        97.5                        16.1                        90.7

                              MFH

                              1                581                        97.8                        13.9                        92.0
                              2                151                        98.4                        14.7                        91.8
                              3                44                         96.7                        19.3                        88.7
                              4                76                         96.9                        19.7                        88.6
                              5                96                         96.4                        20.5                        87.9
                              6                227                        96.3                        16.3                        90.0



    Tables 5 and 6 show the developed archetypes for Uppsala and Got-                     refers to which aspects that mainly distinguish it from the others, as
land with their corresponding cluster parameters and the mean values                      a qualitative analysis determined from the results in Tables 5 and 6.
for each parameter in each cluster. Many archetype values are very                        In Table 7, building energy performance has been labelled from Very
close or similar to the mean value of the cluster, especially for the                     poor to Very good, based on the overall range of values. Building age
building heating systems. One parameter that could possibly be of extra                   is based on the year of construction, where Old refers to buildings
importance is the energy performance (EP), the normal year corrected                      constructed before 1950, Mid refers to the period between 1950-1979,
energy use per area [kWh/m2 ]. Ideally, the EP is the result of many fac-                 Recent from 1980-1999 and Modern from 2000 and later. To quantify or
tors that could inﬂuence the energy demand, including all or most of the                  statistically determine the main distinguishing factor of each archetype,
other clustering parameters. A majority of the archetypes have an EP                      principal component analysis (PCA) or similar feature extraction tech-
value that deviates 5% or less from the cluster mean, and only one with                   niques could be used, but would require a more extensive analysis than
more than 10%. The construction year of the archetype buildings in                        can ﬁt into this paper.
Uppsala range from 1948 to 2013. The most newly built SFH archetype                           To gain a real-world understanding of the cluster characteristics,
also has a very low EP value (52 kWh/m2 ), and the earliest built are                     buildings in a cluster can be observed either on site or using Google
also the ones with the highest EP values. This correlation between con-                   Street View [68], and later analysed in a qualitative manner. For a small
struction year and EP corresponds well with literature [58] and is one                    proof-of-concept study, 20 buildings were selected at random for a ran-
reason for why building stocks are almost always segmented by con-                        dom cluster. The selected random cluster was Uppsala SFH 6, where the
struction year [6,7,9]. However, here we can see that the clustering                      archetype building was observed to be a 1.5 story house with a garage
successfully captures the diﬀerences between similarly aged buildings.                    and a façade of calcium-silicate bricks and wood in a style typical for
For example, Uppsala SFH archetypes 2, 3 and 4 are built during the                       1970s Swedish construction. The sample of cluster buildings were ob-
same construction period, but have drastically diﬀerent other parame-                     served to share similar characteristics. They were nearly all 1-1.5 story
ter values, especially EP.                                                                freestanding houses with garages and similar façades. Four clear outlier
    For Gotland, the construction year ranges from 1929 to 2007, but                      buildings were noted that stood out in the observation. However, all of
with a notable lower likeness between the archetype value and the clus-                   them were larger, mansion-like houses that were recently built.
ter mean. This is also true for most other parameters, which is also
mirrored in the distinctness, as it is generally slightly lower for Got-                  3.4. Geographic distribution
land compared to Uppsala. However, as the diﬀerence is minor, and
as the larger clusters have the highest distinctness, it indicates that the                  Buildings in city areas are not completely heterogeneous by default,
archetypes could still be a good representation of the Gotland building                   and the built environment in diﬀerent areas of a city reﬂects both time
stock as well.                                                                            periods and social development. New city areas are often constructed
    The identiﬁed archetypes and their most deﬁning characteristics are                   as part of large housing projects, resulting in areas with similar or al-
summarised in Table 7. The deﬁning characteristic of an archetype                         most identical buildings. Because of this, a satisfactory clustering result

                                                                                     11
L. Dahlström, F. Johari, T. Broström et al.                                                                                             Energy & Buildings 303 (2024) 113823


                        Table 5
                        Archetype parameters and cluster means (cluster means in parenthesis), Uppsala and Gotland.

                          Archetype      Construction   Building volume   Energy Performance          Income        Age group      Population density
                                         year [yr]      [m3 ]             [kWh/m2 ]                   [kSEK/p,yr]                  [persons/km2 ]
                          Uppsala
                          SFH

                          1              1991 (1989)    702 (589)         99 (96)                     136 (126)     5.6 (5.5)      919 (1019)
                          2              1955 (1961)    713 (746)         126 (133)                   144 (144)     5.9 (6.0)      699 (676)
                          3              1948 (1953)    564 (633)         147 (132)                   140 (132)     5.0 (5.3)      78 (348)
                          4              2006 (2008)    393 (477)         52 (54)                     102 (106)     5.0 (4.8)      358 (409)
                          5              1972 (1963)    624 (630)         121 (117)                   133 (143)     5.6 (5.7)      615 (469)
                          6              1970 (1972)    857 (848)         60 (65)                     132 (150)     6.0 (5.8)      635 (490)
                          7              1968 (1971)    676 (638)         74 (86)                     143 (136)     6.0 (5.6)      360 (396)

                          MFH

                          1              1975 (1981)    3808 (4027)       146 (138)                   131 (136)     5.8 (5.8)      1111 (1106)
                          2              1948 (1942)    5116 (7042)       149 (137)                   173 (178)     5.0 (5.4)      2425 (2434)
                          3              1968 (1963)    5487 (5625)       73 (70)                     113 (125)     5.6 (5.4)      1661 (1545)
                          4              2013 (2001)    10824 (11451)     80 (86)                     144 (152)     5.6 (5.3)      2913 (2600)
                          5              1976 (1976)    1735 (5041)       136 (131)                   87 (100)      5.0 (5.1)      1886 (1897)

                          Gotland
                          SFH

                          1              1971 (1966)    677 (622)         73 (78)                     143 (127)     5.9 (5.6)      60 (87)
                          2              1950 (1959)    496 (616)         105 (114)                   145 (123)     5.7 (5.6)      138 (147)
                          3              1943 (1965)    665 (864)         110 (133)                   119 (145)     6.0 (5.9)      512 (479)
                          4              1950 (1950)    711 (645)         77 (75)                     138 (145)     5.8 (6.0)      475 (509)
                          5              1930 (1942)    506 (648)         174 (175)                   128 (123)     5.7 (5.6)      23 (118)
                          6              1984 (1958)    602 (603)         85 (99)                     164 (121)     5.9 (5.6)      102 (106)
                          7              1968 (1957)    725 (577)         121 (126)                   135 (131)     5.6 (5.7)      111 (169)

                          MFH

                          1              1968 (1976)    2478 (3265)       134 (135)                   131 (148)     6.0 (5.8)      670 (621)
                          2              1972 (1982)    3477 (2934)       128 (126)                   107 (110)     3.9 (4.0)      205 (294)
                          3              1980 (1967)    1288 (1949)       101 (127)                   134 (122)     5.3 (5.7)      176 (243)
                          4              1929 (1947)    1318 (2599)       100 (78)                    171 (182)     5.9 (6.1)      242 (285)
                          5              1931 (1968)    1614 (1686)       134 (125)                   108 (123)     6.0 (5.8)      289 (230)
                          6              1968 (1957)    5785 (3608)       104 (134)                   200 (248)     5.8 (6.1)      266 (285)



would give clusters that are well distributed geographically; some clus-                   on the construction year parameter could possibly steer the algorithm
ters are more represented in some areas rather than other, and areas                       to produce archetypes also for these areas.
will have one cluster that is dominant.
    Figs. 8–12 show the geographical locations of the examined build-                      4. Discussion
ings within Uppsala and on Gotland, coloured after the ﬁnalised clus-
ters, along with the corresponding building archetypes. Figs. 11 and 13                    4.1. Results and identiﬁed archetypes
are magniﬁed to show the city of Visby, Gotland in more detail. The
building clusters are clearly distinct by location, and the distribution                       The fundamental application for identiﬁed building archetypes is
of clusters varies between diﬀerent areas. Clusters are not distributed                    the inclusion and aggregation into a fully realised UBEM. Recently,
by area in any particular pattern on Gotland, and this heterogeneous                       Johari et al. [69] developed an accurate UBEM based on available na-
distribution of clusters is as expected from a rural building stock. No-                   tional open data in Sweden, using GIS and EPC data and a simpliﬁed
table, however, is that some clusters are almost only represented in                       deterministic approach for building archetype classiﬁcation. Using this
either the city or the countryside. This result conﬁrms the hypothe-                       framework, an UBEM could be developed using the building archetypes
sis that buildings in the same area are more likely to belong to the                       from this study. A goal for future research would be to analyse the po-
same cluster. With a knowledge of the study areas, the geographical                        tential for accuracy improvement using the detailed archetypes, and
distribution of the clusters also shows that the algorithm is capable of                   the use of random sampling from archetype parameter distributions
identifying characteristic patterns in the building stock. For example, it                 when aggregating the archetypes to large-scale models. The procedure
can be noted that student-housing areas and socio-economically disad-                      is capable of identifying patterns in the building stock, including socio-
vantaged areas in Uppsala are clearly represented as belonging to one                      economically diverse areas. Future UBEM work could include investi-
cluster, MFH 5, which has the lowest income and low mean age. This                         gation of energy use patterns in the building stock and evaluation of
feature can be used in a future UBEM to evaluate certain areas, such as                    the potential of UBEM for speciﬁc areas or building types. It can also
socio-economically vulnerable areas, more in detail or compare them to                     be useful for the simulation procedure itself as socio-economic diﬀer-
other areas more accurately.                                                               ences aﬀect building occupancy, and improving occupancy modelling is
    For both case studies it can however be noted that no archetype is                     crucial for improved accuracy. Residential occupancy has been shown
located in the city centres of Uppsala and Visby (although clusters are                    to be highly neighbourhood dependent [70], so a way of determining
present there). Both city centres are densely built with high human ac-                    these diﬀerences without the need of in-depth data acquisition could be
tivity, as is typical, and have a high share of non-residential buildings.                 highly useful.
To be able to accurately capture the characteristics of these areas, it                        Multivariate cluster analysis can be a signiﬁcant aid when identify-
could be of interest to deterministically deﬁne one or several archetypes                  ing archetypes based on multiple parameters and open data sets, and at
for these areas beforehand. Since a large share of the city centre build-                  a low cost. The developed procedure allows to partially overcome the
ings is historical, especially in the city of Visby, to put a weighting factor             issue of data scarcity in urban data sets, which is often discussed in lit-

                                                                                      12
L. Dahlström, F. Johari, T. Broström et al.                                                                                       Energy & Buildings 303 (2024) 113823


                                                                                   Table 6
                                                                                   Archetype parameters and cluster means (cluster means in parenthesis), Upp-
                                                                                   sala and Gotland.

                                                                                    Archetype      Share of           Share of      Share of            Share of
                                                                                                   district heating   boilers       Electric heating    heat pumps

                                                                                    Uppsala
                                                                                    SFH

                                                                                    1              1.0 (0.9)          0.0 (0.0)     0.1 (0.1)           0.0 (0.0)
                                                                                    2              1.0 (1.0)          0.0 (0.0)     0.0 (0.0)           0.0 (0.0)
                                                                                    3              0.0 (0.0)          0.9 (0.8)     0.1 (0.1)           0.0 (0.1)
                                                                                    4              0.0 (0.0)          0.0 (0.0)     0.1 (0.1)           0.9 (0.9)
                                                                                    5              0.0 (0.0)          0.0 (0.0)     1.0 (0.9)           0.0 (0.0)
                                                                                    6              0.0 (0.0)          0.0 (0.0)     0.1 (0.1)           0.9 (0.9)
                                                                                    7              0.0 (0.0)          0.1 (0.1)     0.5 (0.6)           0.4 (0.4)

                                                                                    MFH

                                                                                    1              0.9 (0.9)          0.0 (0.0)     0.1 (0.1)           0.0 (0.0)
                                                                                    2              0.9 (1.0)          0.0 (0.0)     0.1 (0.1)           0.0 (0.0)
                                                                                    3              0.3 (0.1)          0.0 (0.0)     0.2 (0.3)           0.6 (0.6)
                                                                                    4              0.8 (0.7)          0.0 (0.0)     0.3 (0.2)           0.0 (0.1)
                                                                                    5              0.9 (0.9)          0.0 (0.0)     0.1 (0.1)           0.0 (0.0)

                                                                                    Gotland
                                                                                    SFH

                                                                                    1              0.0 (0.0)          0.0 (0.0)     0.1 (0.1)           0.9 (0.9)
                                                                                    2              0.0 (0.0)          0.2 (0.2)     0.5 (0.6)           0.3 (0.2)
                                                                                    3              1.0 (1.0)          0.0 (0.0)     0.0 (0.0)           0.0 (0.0)
                                                                                    4              0.0 (0.0)          0.0 (0.0)     0.0 (0.1)           1.0 (0.9)
                                                                                    5              0.0 (0.0)          0.9 (0.9)     0.1 (0.1)           0.0 (0.0)
                                                                                    6              0.0 (0.0)          0.4 (0.4)     0.2 (0.1)           0.4 (0.5)
                                                                                    7              0.0 (0.0)          0.0 (0.0)     1.0 (1.0)           0.0 (0.0)

                                                                                    MFH

                                                                                    1              1.0 (0.9)          0.0 (0.0)     0.0 (0.1)           0.0 (0.0)
                                                                                    2              0.9 (0.9)          0.0 (0.0)     0.1 (0.1)           0.0 (0.0)
                                                                                    3              0.0 (0.0)          0.9 (0.9)     0.1 (0.1)           0.0 (0.0)
                                                                                    4              0.0 (0.0)          0.0 (0.0)     0.1 (0.1)           0.9 (0.9)
                                                                                    5              0.0 (0.0)          0.0 (0.0)     1.0 (1.0)           0.0 (0.1)
                                                                                    6              0.9 (0.9)          0.0 (0.0)     0.1 (0.1)           0.0 (0.0)




     Fig. 7. RMSSTD (a) and median distinctness (b) for MFH on Gotland.




    Fig. 8. Identiﬁed clusters and archetypes for SFH buildings in Uppsala.             Fig. 9. Identiﬁed clusters and archetypes for MFH buildings in Uppsala.


                                                                              13
L. Dahlström, F. Johari, T. Broström et al.                                                                                                   Energy & Buildings 303 (2024) 113823


                                 Table 7
                                 Overview characterisation of the identiﬁed building archetypes, with energy performance graded from Very
                                 poor to Very good, and Building age categorised as the construction periods Old <1950, Mid 1950-1979, Recent
                                 1980-1999 and Modern 2000-present.

                                   Archetype   Energy          Heating system                Building age   Other deﬁning indicators
                                               performance

                                   Uppsala
                                   SFH

                                   1           Medium          District heating              Recent         High population density
                                   2           Poor            District heating              Mid            High income
                                   3           Poor            Boilers                       Old            Young residents, low population density
                                   4           Very good       Heat pumps                    Modern         Low income, young residents
                                   5           Poor            Electric heating              Mid            -
                                   6           Good            Heat pumps                    Mid            Large volume
                                   7           Good            Mixed                         Mid            High income

                                   MFH

                                   1           Poor            District heating              Mid            Old residents
                                   2           Poor            District heating              Old            High income, high population density
                                   3           Good            Mixed, with heat pumps        Mid            -
                                   4           Good            Mixed, no heat pumps          Modern         Large volume, high population density
                                   5           Poor            District heating              Mid            Low income, young residents

                                   Gotland
                                   SFH

                                   1           Good            Heat pumps                    Mid            Low population density, rural
                                   2           Medium          Mixed                         Mid            High population density, rural
                                   3           Medium          District heating              Old            High population density, urban
                                   4           Good            Heat pumps                    Mid            High population density, urban
                                   5           Very poor       Boilers                       Old            Low population density, rural
                                   6           Good            Mixed                         Recent         High income
                                   7           Poor            Electric heating              Mid            Large volume

                                   MFH

                                   1           Poor            District heating              Mid            High population density
                                   2           Poor            District heating              Mid            Low income, young residents
                                   3           Medium          Boilers                       Recent         Low population density
                                   4           Medium          Heat pumps                    Old            High income
                                   5           Poor            Electric heating              Old            Low income
                                   6           Medium          District heating              Mid            High income



erature. As it utilises open data and a thoroughly described process the                      Statistical data that can be tied to individuals, households or build-
study can be replicated, which we see as a major beneﬁt of the pro-                           ings would evidently improve the accuracy signiﬁcantly, but are not
cedure. Using k-means clustering of multiple variables, 12 archetypes                         open data, which means using them would go against the aim of this
were identiﬁed for the residential building stocks in Uppsala and 13 on                       study.
Gotland. The identiﬁed archetypes are representative of their respective                          The increased number of parameters does give more depth to the
cluster of building data points, but are also diverse among themselves,                       identiﬁed archetypes as they contain more information about the char-
covering a wide range of building characteristics.                                            acteristics of their corresponding clusters, and allows for the division
    The clustering algorithm worked well with parameters not often                            of the building stock based on other aspects than those traditionally
used in the ﬁeld, namely socio-economic indicators and building heat-                         used. When analysing the results (Tables 5 to 7) signiﬁcant patterns can
ing systems. Adding more parameters in the clustering process de-                             be clearly noted. Building heating system seems to be a decisive fac-
creases the overall accuracy as more uncertainties are introduced, and                        tor for both the building EP and the division into archetypes, and the
the representativeness is measured against additional parameters. Run-                        socio-economic parameters are often the divisive factor distinguishing
ning the procedure with a higher number of parameters also results in a                       two archetypes with similar heating system and construction period.
higher number of archetypes, compared to running with fewer parame-                           This could be of importance to future UBEM applications targeting or
ters, but this is expected as the building stock then can be divided based                    comparing certain city areas or building types. The importance of the
on more factors.                                                                              heating system for the EP of a building can also be seen in the results as
    The use of spatial interpolation of statistical data also introduces                      the EP values are clearly diﬀerent between the archetypes. This implies
uncertainties. In addition to uncertainties in the underlying data, un-                       that the division into archetypes by building heating systems could be
certainty in spatial models is dependent on the resolution of spa-                            important for the later UBEM stages, as a way to increase model accu-
tial data, the spatial autocorrelation of the parameter values, that is                       racy and to mitigate the performance-simulation gap.
the degree of correlation or similarity between nearby observations,                              Buildings that are not present in the EPC data set need to be charac-
and the interpolation grid size [71]. The interpolation is based on                           terised when applying the UBEM over the whole area, where the central
data points representing the parameter mean values for all buildings                          step is to assign them into the right archetype. As the socio-economic
within 250×250 m squares, which could eradicate the inherent dif-                             data is available for the entire area, the diﬀerences in these parameters
ferences between buildings within this area, and limits the resolution                        between the archetypes could greatly improve the assigning of these
of spatial data to 250 m. The use of spatial interpolation for this                           buildings into the most representative archetype. Furthermore, to anal-
procedure relies on the assumption that neighbouring areas are more                           yse the main distinguishing factors in depth and their signiﬁcance for
similar (see Section 3.4) also regarding socio-economic indicators, in                        archetype classiﬁcation, using for example PCA techniques, could be
this case corresponding to a high degree of parameter autocorrelation.                        rewarding for future research.

                                                                                        14
L. Dahlström, F. Johari, T. Broström et al.                                                                            Energy & Buildings 303 (2024) 113823




                                                                                    Fig. 11. Identiﬁed clusters and archetypes for SFH in Visby.

         Fig. 10. Identiﬁed clusters and archetypes for SFH on Gotland.


4.2. Clustering procedure

    The use of k-means clustering and the elbow method to identify
building archetypes is common in the ﬁeld. However, the wide selection
of clustering parameters utilised in this study, namely building heating
systems, socio-economic factors and measured energy performance, is
not. Additionally, the analysis of the divergence point of the error met-
ric to determine the maximum amount of stable clusters has to our
knowledge not been previously utilised. Most studies either apply an
overly simple analysis and a deterministic way to decide the value of
k, or apply a computation-heavy, time-consuming analysis of multiple
methods and indices. There is also the considerable issue regarding the
lack of similar studies that are capable of replication, indicating the im-
portance of studies utilising openly available data sets and an adaptable
methodology.
    Both the RMSSTD and distinctness indices were shown to be useful
tools when determining the optimal number of clusters, complementing
each other eﬀectively and providing useful visual representation. How-
ever, the approach to determine 𝑘 by identifying the inﬂection point,
or “elbow”, in the RMSSTD curve [13,19] does not work if the result-
ing graph does not have an elbow or if it has multiple elbows. As shown
in this paper, the RMSSTD curve could also be misguiding if one does
not account for the possible divergence between iterations due to the
“forced clustering”. This analysis of the divergence between algorithm
iterations is important for getting reliable results out of the clustering
technique and is possibly completely new to the ﬁeld. These ﬁndings
may have potential implications for utilising simple error metrics when
evaluating cluster analysis results, which could be further investigated
in future research. For validating cluster analysis, it has been pointed
out that the degree of consistency in algorithm runs indicates reliability
[60] and that for strong conﬁdence in the results, techniques that are             Fig. 12. Identiﬁed clusters and archetypes for MFH on Gotland.


                                                                              15
L. Dahlström, F. Johari, T. Broström et al.                                                                                    Energy & Buildings 303 (2024) 113823


                                                                                     impact the performance of UBEMs would require applying the resulting
                                                                                     archetypes to large-scale UBEM simulations and comparing the results
                                                                                     against measurement data. This is a too extensive analysis to include in
                                                                                     this paper, but would be interesting as a future study.
                                                                                          For geometric data, there exist several open standardised geospa-
                                                                                     tial data formats, including CityGML [72] or OpenStreetMap [73], that
                                                                                     have recently gained popularity as comprehensive data formats to use
                                                                                     for UBEM [10,22]. These formats contain useful information about the
                                                                                     urban environment but are not always available for urban areas and
                                                                                     usually lack vital building information [22,74]. For the scope of this
                                                                                     paper, a 3D representation of the full studied building stock was not
                                                                                     needed as the 2D cadastral data provided all vital information for the
                                                                                     used approach. For later stages of UBEM development, which includes
                                                                                     3D model development, the archetypes identiﬁed in this paper could
                                                                                     still be used even when applying CityGML or similar formats for these
                                                                                     stages, given that key geospatial characteristics such as building foot-
                                                                                     print and position are consistent in the respective data formats.
                                                                                          The study was based on EPCs, which provide very useful data but
                                                                                     only cover a part of the building stock, creating a sample bias. The
                                                                                     share of buildings that do have an EPC is smaller for SFH compared to
                                                                                     MFH, even more so for rural SFH, and the study left out non-residential
                                                                                     buildings for similar reasons. UBEMs often aim to include all build-
                                                                                     ings, including non-residential buildings such as oﬃces, schools, and
                                                                                     industry. Oﬃces or mixed-use buildings have been included in, or have
                                                                                     been the main focus of, similar studies using a clustering approach
                                                                                     [14,17,19]. The number of other non-residential buildings (schools,
                                                                                     hospitals, etc.) is generally low compared to other use types, so us-
                                                                                     ing separate archetypes for these building types is often unnecessary.
                                                                                     Future UBEMs can utilise assumptions made from previous studies, or
                                                                                     apply individual BEM if metered data is unavailable.
                                                                                          Upscaling of data to city-scale level is necessary for the UBEM pro-
           Fig. 13. Identiﬁed clusters and archetypes for MFH in Visby.
                                                                                     cess, regardless of using EPCs or other data sources to identify and
                                                                                     characterise the archetypes, and is highly important for further research
less subject to the bias of researchers must be used. This reliability is in-        following the developed methodology. For this process there are two
creased by running the algorithm for several iterations and noticing the             major uncertainties; to assign all buildings the appropriate archetype
divergence point, as shown in this paper.                                            and characterisation, and the accuracy of archetypes in terms of rep-
    Our proposed index, the cluster distinctness, focuses on the compact-            resenting the entire building stock. The insuﬃcient coverage of some
ness of each cluster (same as RMSSTD) but not on the distance between                data is aﬀecting the accuracy of the archetypes, which also is the fo-
each cluster. It also focuses more on the mean value for each parame-                cus of this paper. For the later-stage UBEM processes, measures can be
ter for each cluster, and puts equal weight on how representative the                taken to ensure higher accuracy or data coverage since it is known for
archetype building is of said cluster. Algorithms that use a large num-              which buildings data is missing. Data for buildings without EPCs could
ber of diﬀerent indices to determine the optimal clustering method and               be obtained by resorting to other sources, for example by collecting
number of clusters (like NbClust) exist and work well; however, the                  new data through inventory studies or by manually deﬁning archetypes
computational time for such algorithms is signiﬁcant and they usually                for these buildings in a deterministic fashion. Two separate analyses
provide no means of visualisation. Every diﬀerent index also has slightly            could also be performed and later combined to identify archetypes; one
diﬀerent targets; depending on what is important for each study, diﬀer-              for EPC parameters and one for building volume and socio-economic
ent indices may be the most useful. When used for similar applications,              parameters, which are available for the whole building stock with the
this algorithm does however seem to produce only very low values of                  approach used in this paper. To ensure the identiﬁcation accuracy also
𝑘 (see Section 2.6), which results in a number of clusters too small for             for rural SFH, a better insight into the actual composition of the build-
many applications.                                                                   ing stock is needed. It is necessary to ascertain if our assumption is
                                                                                     correct, or if the distribution of building characteristics is skewed com-
4.3. Limitations and areas for further research                                      pared to reality. A study performing a more detailed inventory of a
                                                                                     selected area, for example a countryside parish, and comparing with
    The choice of clustering technique and metrics for assessing cluster             data and archetypes from this study, would be helpful in validating the
quality can be subjective; choosing a diﬀerent method or metric will                 methodology. We have made the assumption that the EPCs are a good
most certainly yield diﬀerent results since the criteria for deﬁning the             representation of the building stock despite the smaller sample size and
optimal clusters would change. The choice of method and metric in this               that the distribution of parameter values is statistically accurate on an
paper was made based on a literature review of similar studies, where                aggregate level. Furthermore, the EPCs in the EU are about to be ex-
k-means and RMSSTD where shown to be the most promising clustering                   tended and harmonised between all member states, as pointed out in
method and quality metric, respectively. Since the aim of this study was             Section 1.3. With better comparability there will be even more areas
to evaluate the cluster analysis of an extended number of parameters,                with the ability to adapt the procedures developed in this study, and
which was successful using the chosen method, this approach can be                   the accuracy of the approach will increase with increasing EPC cover-
taken using alternative clustering methods. A comparison of diﬀerent                 age across the building stocks. Additionally, even as the coverage per
clustering techniques and metrics for an extended set of parameters                  capita in Sweden is increasing, it is not currently in the top ﬁve of Eu-
could be useful for future research in the area. A deﬁnite evaluation                rope [34] which indicates that the accuracy would be even higher for
of how diﬀerent clustering techniques and choices of metrics would                   other European building stocks.

                                                                                16
L. Dahlström, F. Johari, T. Broström et al.                                                                                            Energy & Buildings 303 (2024) 113823


    The developed methodology represents the ﬁrst step towards devel-              References
oping a novel UBEM approach for the building stock in Sweden or any
country with similar availability of open data sets. Following the scope            [1] European Union, Final energy consumption by sector, https://ec.europa.eu/
                                                                                        eurostat/databrowser/view/ten00124/default/table?lang=en. (Accessed 20 Jan-
of this paper, the successive strategy is to apply this method and the
                                                                                        uary 2023), 2022.
resulting archetypes in a large-scale UBEM, where the analysis, descrip-            [2] D. Wu, J.C. Lin, T. Oda, E.A. Kort, Space-based quantiﬁcation of per capita co2
tion and characterisation of the identiﬁed archetypes are left to future                emissions from cities, Environ. Res. Lett. 15 (2020) 035004, https://dx.doi.org/10.
studies.                                                                                1088/1748-9326/ab68eb.
                                                                                    [3] H. Ritchie, M. Roser Urbanization, Our world in data, https://ourworldindata.org/
                                                                                        urbanization, 2018.
5. Conclusions
                                                                                    [4] European Commission, 2030 climate & energy framework, https://
                                                                                        climate.ec.europa.eu/eu-action/climate-strategies-targets/2030-climate-energy-
    This paper presented a replicable methodology to identify archetype                 framework_en. (Accessed 20 January 2023), 2023.
buildings by using a simple yet reliable algorithm using k-means clus-              [5] S. Cajot, M. Peter, J.-M. Bahu, A. Koch, F. Maréchal, Energy planning in the urban
                                                                                        context: challenges and perspectives, Energy Proc. 78 (2015) 3366–3371, https://
tering, which was applied to two case studies of the Swedish residential
                                                                                        doi.org/10.1016/j.egypro.2015.11.752, 6th International Building Physics Confer-
building stock. The proposed procedure is computationally fast and                      ence, IBPC 2015.
can be made automated which can signiﬁcantly simplify database pre-                 [6] F. Johari, G. Peronato, P. Sadeghian, X. Zhao, J. Widén, Urban building energy
handling eﬀorts. Furthermore, it requires only open data; this makes                    modelling: state of the art and future prospects, Renew. Sustain. Energy Rev. 128
the methodology easy to apply to diﬀerent areas and thus useful for                     (2020) 109902, https://doi.org/10.1016/j.rser.2020.109902.
                                                                                    [7] L. Dahlström, T. Broström, J. Widén, Advancing urban building energy modelling
comparing results, which is proven by performing the analysis on two
                                                                                        through new model components and applications: a review, Energy Build. 266
large data sets. The developed procedure can be applied in future UBEM                  (2022) 112099, https://doi.org/10.1016/j.enbuild.2022.112099.
studies of any area with similar availability of open data sets. Addition-          [8] O. Pasichnyi, J. Wallin, F. Levihn, H. Shahrokni, O. Kordas, Energy performance
ally, the relevance of the approach is only expected to rise as it will                 certiﬁcates — new opportunities for data-enabled urban energy policy instruments?,
have an increased application ﬁeld along with the current increase in                   Energy Policy 127 (2019) 486–499, https://doi.org/10.1016/j.enpol.2018.11.051.
                                                                                    [9] C.F. Reinhart, C. Cerezo Davila, Urban building energy modelling – a review of
availability and coverage of energy performance certiﬁcates in the EU.                  a nascent ﬁeld, Build. Environ. 97 (2016) 196–202, https://doi.org/10.1016/j.
Combined with a reliable approach to aggregate the result for the build-                buildenv.2015.12.001.
ings that are not present in the used data set, these studies can apply the        [10] U. Ali, M.H. Shamsi, C. Hoare, E. Mangina, J. O’Donnell, Review of urban build-
methodology to identify archetype buildings that are representative of                  ing energy modelling (ubem) approaches, methods and tools using qualitative and
                                                                                        quantitative analysis, Energy Build. 246 (2021) 111073, https://doi.org/10.1016/j.
the studied building stock, which can later be used to develop a reliable
                                                                                        enbuild.2021.111073.
and accurate UBEM.                                                                 [11] N. Ghiassi, A. Mahdavi, Reductive bottom-up urban energy computing supported by
    The algorithm is able to identify visible patterns in the studied                   multivariate cluster analysis, Energy Build. 144 (2017) 372–386, https://doi.org/
building stocks, which are transferred to the building archetypes. With                 10.1016/j.enbuild.2017.03.004.
this approach, archetypes display diﬀerences in building heating sys-              [12] G. Tardioli, A. Narayan, R. Kerrigan, M. Oates, J. O’Donnell, D.P. Finn, A method-
                                                                                        ology for calibration of building energy models at district scale using clustering and
tems and can represent socio-economically diﬀerentiated areas, and the                  surrogate techniques, Energy Build. 226 (2020) 110309, https://doi.org/10.1016/j.
archetypes are characterised by parameter distributions which could be                  enbuild.2020.110309.
useful for aggregation to larger scale. When determining the optimal               [13] M. Halkidi, Y. Batistakis, M. Vazirgiannis, On clustering validation techniques, J. In-
number of clusters an augmented version of the simple elbow method                      tell. Inf. Syst. (2001) 107–145.
                                                                                   [14] G. Tardioli, R. Kerrigan, M. Oates, J. O’Donnell, D.P. Finn, Identiﬁcation of represen-
is suﬃcient to develop representative building clusters. Complementary
                                                                                        tative buildings and building groups in urban datasets using a novel pre-processing,
to ﬁnding the elbow for the error metric, the cluster distinctness and di-              classiﬁcation, clustering and predictive modelling approach, Build. Environ. 140
vergence point for determining the maximum number of clusters are                       (2018) 90–106, https://doi.org/10.1016/j.buildenv.2018.05.035.
evaluated. The resulting clusters are well deﬁned, both parameter-wise             [15] D. Hsu, Comparison of integrated clustering methods for accurate and stable pre-
and by geographic distribution. This indicates that the methodology                     diction of building energy consumption data, Appl. Energy 160 (2015) 153–163,
                                                                                        https://doi.org/10.1016/j.apenergy.2015.08.126.
better captures the diversity of building characteristics within the build-
                                                                                   [16] X. Deng, Z. Tan, M. Tan, W. Chen, A clustering-based climatic zoning method for
ing stock, including socio-economic parameters, compared to typical                     oﬃce buildings in China, J. Build. Eng. 42 (2021) 102778, https://doi.org/10.1016/
deterministic segmentation.                                                             j.jobe.2021.102778.
    In this paper, we have shown that this approach is useful for iden-            [17] P. Borges, O. Travesset-Baro, A. Pages-Ramon, Hybrid approach to representative
                                                                                        building archetypes development for urban models – a case study in andorra, Build.
tifying building archetypes, that the method is reliable and easily
                                                                                        Environ. 215 (2022) 108958, https://doi.org/10.1016/j.buildenv.2022.108958.
adapted, and that the resulting archetype buildings are representative             [18] I. De Jaeger, G. Reynders, C. Callebaut, D. Saelens, A building clustering approach
for their respective clusters – mainly in terms of the numerical metrics                for urban energy simulations, Energy Build. 208 (2020) 109671, https://doi.org/
employed but also as suggested by a small qualitative analysis – which                  10.1016/j.enbuild.2019.109671.
indicates an accurate representation of the studied building stock.                [19] M. Gangolells, M. Casals, J. Ferré-Bigorra, N. Forcada, M. Macarulla, K. Gaspar, B.
                                                                                        Tejedor, Oﬃce representatives for cost-optimal energy retroﬁtting analysis: a novel
                                                                                        approach using cluster analysis of energy performance certiﬁcate databases, Energy
CRediT authorship contribution statement                                                Build. 206 (2020) 109557, https://doi.org/10.1016/j.enbuild.2019.109557.
                                                                                   [20] C. Wang, M. Ferrando, F. Causone, X. Jin, X. Zhou, X. Shi, Data acquisition for urban
   Lukas Dahlström: Conceptualization, Methodology, Writing – orig-                     building energy modelling: a review, Build. Environ. 217 (2022) 109056, https://
                                                                                        doi.org/10.1016/j.buildenv.2022.109056.
inal draft, Software. Fatemeh Johari: Methodology. Tor Broström:
                                                                                   [21] W. Li, Y. Zhou, K. Cetin, J. Eom, Y. Wang, G. Chen, X. Zhang, Modeling urban
Supervision, Writing – review & editing. Joakim Widén: Supervision,                     building energy use: a review of modelling approaches and procedures, Energy 141
Writing – review & editing.                                                             (2017) 2445–2457, https://doi.org/10.1016/j.energy.2017.11.071.
                                                                                   [22] A. Malhotra, J. Bischof, A. Nichersu, K.-H. Häfele, J. Exenberger, D. Sood, J. Allan,
Declaration of competing interest                                                       J. Frisch, C. van Treeck, J. O’Donnell, G. Schweiger, Information modelling for ur-
                                                                                        ban building energy simulation—a taxonomic review, Build. Environ. 208 (2022)
                                                                                        108552, https://doi.org/10.1016/j.buildenv.2021.108552.
    The authors declare that they have no known competing ﬁnancial                 [23] Institut Wohnen und Umwelt GmbH, IEE project EPISCOPE, https://episcope.eu/
interests or personal relationships that could have appeared to inﬂuence                welcome/. (Accessed 28 August 2023), 2016.
the work reported in this paper.                                                   [24] Enerdata, Odyssee database, https://www.indicators.odyssee-mure.eu/energy-
                                                                                        eﬃciency-database.html. (Accessed 28 August 2023), 2023.
                                                                                   [25] C. Cerezo, J. Sokol, S. AlKhaled, C. Reinhart, A. Al-Mumin, A. Hajiah, Compari-
Data availability                                                                       son of four building archetype characterization methods in urban building energy
                                                                                        modelling (ubem): a residential case study in Kuwait city, Energy Build. 154 (2017)
    The authors do not have permission to share data.                                   321–334, https://doi.org/10.1016/j.enbuild.2017.08.029.


                                                                              17
L. Dahlström, F. Johari, T. Broström et al.                                                                                                             Energy & Buildings 303 (2024) 113823


[26] Boverket, Ska din byggnad ha en energideklaration?, https://www.boverket.se/sv/               [49] G. Happle, J. Fonseca, A. Schlueter, A review on occupant behavior in urban
     energideklaration/energideklaration/. (Accessed 20 January 2023), 2022.                            building energy models, Energy Build. (2018) 276–292, https://doi.org/10.1016/
[27] C. Hjortling, F. Björk, M. Berg, T. af Klintberg, Energy mapping of existing building              j.enbuild.2018.06.030.
     stock in Sweden – analysis of data from energy performance certiﬁcates, Energy                [50] European Parliament, General data protection regulation, https://gdprinfo.eu/. (Ac-
     Build. (2017) 341–355, https://doi.org/10.1016/j.enbuild.2017.06.073.                              cessed 20 January 2023), 2016.
[28] M. Mangold, M. Österbring, H. Wallbaum, Handling data uncertainties when using                [51] A. Hayes, Empirical rule: deﬁnition, formula, example, how it’s used, https://www.
     Swedish energy performance certiﬁcate data to describe energy usage in the build-                  investopedia.com/terms/e/empirical-rule.asp. (Accessed 20 January 2023), 2022.
     ing stock, Energy Build. 102 (2015) 328–336, https://doi.org/10.1016/j.enbuild.               [52] Oxford College of Emory University Department of Mathematics and Computer Sci-
     2015.05.045.                                                                                       ence, Chebyshev’s theorem, https://mathcenter.oxford.emory.edu/site/math117/
[29] Boverket,       Energideklarationens       innehåll,    https://www.boverket.se/sv/                chebyshev/. (Accessed 20 January 2023), 2023.
     energideklaration/energideklaration/energideklarationens-innehall/. (Accessed 30              [53] G.W. Milligan, M.C. Cooper, A study of standardization of variables in cluster anal-
     August 2023), 2023.                                                                                ysis, J. Classif. 5 (1988) 181–204.
[30] European Commission, Directorate-General for Energy, Proposal for a directive of              [54] A. David, S. Vassilvitskii K-means++, The advantages of careful seeding, in: SODA
     the European Parliament and of the council on the energy performance of buildings                  ’07: Proceedings of the Eighteenth Annual ACM-SIAM Symposium on Discrete Algo-
     (recast), Technical Report, ENER, 2021.                                                            rithms, 2007, pp. 1027–1035.
[31] J. von Platten, C. Holmberg, M. Mangold, T. Johansson, K. Mjörnell, The renew-                [55] A.K. Jain, M.N. Murty, P.J. Flynn, Data clustering: a review, ACM Comput. Surv. 31
     ing of energy performance certiﬁcates — reaching comparability between decade-                     (1999) 264–323, https://doi.org/10.1145/331499.331504.
     apart energy records, Appl. Energy (2019), https://doi.org/10.1016/j.apenergy.                [56] The MathWorks Inc., kmeans, https://www.mathworks.com/help/stats/kmeans.
     2019.113902.                                                                                       html. (Accessed 20 February 2023), 2023.
[32] G. Mutani, V. Todeschi, GIS-based urban energy modelling and energy eﬃciency                  [57] O. Pasichnyi, J. Wallin, O. Kordas, Data-driven building archetypes for urban build-
     scenarios using the energy performance certiﬁcate database, Energy Eﬀ. (2021),                     ing energy modelling, Energy (2019) 360–377, https://doi.org/10.1016/j.energy.
     https://doi.org/10.1007/s12053-021-09962-z.                                                        2019.04.197.
[33] T. Johansson, T. Olofsson, M. Mangold, Development of an energy atlas for renova-             [58] U. Ali, M.H. Shamsi, C. Hoare, E. Mangina, J. O’Donnell, A data-driven approach
     tion of the multifamily building stock in Sweden, Appl. Energy 203 (2017) 723–736,                 for multi-scale building archetypes development, Energy Build. 202 (2019) 109364,
     https://doi.org/10.1016/j.apenergy.2017.06.027.                                                    https://doi.org/10.1016/j.enbuild.2019.109364.
[34] J. Volt, S. Zuhaib, S. Schmatzberger, Z. Toth, Energy Performance Certiﬁcates - As-           [59] C. Shi, B. Weia, S. Wei, W. Wang, H. Liu, J. Liu, A quantitative discriminant method
     sessing their status and potential, Technical Report, Buildings Performance Institute              of elbow point for the optimal number of clusters in clustering algorithm, EURASIP
     Europe (BPIE), 2020.                                                                               J. Wirel. Commun. Netw. (2021), https://doi.org/10.1186/s13638-021-01910-w.
[35] European Commission, data.europa.eu - the oﬃcial portal for European data,                    [60] J. David, J. Ketchen, C.L. Shook, The application of cluster analysis in strategic man-
     https://data.europa.eu/en. (Accessed 23 August 2023), 2023.                                        agement research: an analysis and critique, Strateg. Manag. J. 17 (1996) 441–458,
[36] Lantmäteriet, Lantmäteriet, https://www.lantmateriet.se/. (Accessed 20 January                     https://www.jstor.org/stable/2486927.
     2023), 2023.                                                                                  [61] P.J. Rousseeuw, Silhouettes: a graphical aid to the interpretation and validation of
[37] Statistikmyndigheten, Statistikmyndigheten, https://www.scb.se/. (Accessed 20                      cluster analysis, J. Comput. Appl. Math. 20 (1987) 53–65, https://doi.org/10.1016/
     January 2023), 2023.                                                                               0377-0427(87)90125-7.
[38] Boverket, Normalisering av energianvändningen, https://www.boverket.se/sv/PBL-                [62] D. Pelleg, A. Moore, X-means: extending k-means with eﬃcient estimation of the
     kunskapsbanken/regler-om-byggande/boverkets-byggregler/energihushallning/                          number of clusters, in: ICML ’00: Proceedings of the Seventeenth International Con-
     byggnadens-energianvandning-baserad-pa-matning/normalisering-av-                                   ference on Machine Learning, 2000, pp. 727–734.
     energianvandningen/. (Accessed 20 January 2023), 2022.                                        [63] G.W. Robert Tibshirani, T. Hastie, Estimating the number of clusters in a data set via
[39] SMHI, Ny normalperiod för smhi graddagar, smhi energi-index och smhi kyl-index,                    the gap statistic, J. R. Stat. Soc., Ser. B, Stat. Methodol. 63 (2001) 411–423, https://
     https://www.smhi.se/professionella-tjanster/nyhetsarkiv-professionella-tjanster/                   doi.org/10.1111/1467-9868.00293.
     ny-normalperiod-for-smhi-graddagar-smhi-energi-index-och-smhi-kyl-index-1.                    [64] M. Charrad, N. Ghazzali, V. Boiteau, A. Niknafs, Nbclust: an r package for deter-
     180915. (Accessed 20 January 2023), 2022.                                                          mining the relevant number of clusters in a data set, J. Stat. Softw. 61 (2014) 1–36,
[40] H. Ledoux, F. Biljecki, B. Dukai, K. Kumar, R. Peters, J. Stoter, T. Commandeur,                   http://www.jstatsoft.org/v61/i06/.
     3dﬁer: automatic reconstruction of 3d city models, J. Open Sour. Softw. 6 (2021)              [65] Y. Li, C. Liu, L. Zhang, B. Sun, A partition optimization design method for a re-
     2866, https://doi.org/10.21105/joss.02866.                                                         gional integrated energy system based on a clustering algorithm, Energy 219 (2021)
[41] R.V. Jones, A. Fuertes, K.J. Lomas, The socio-economic, dwelling and appliance                     119562, https://doi.org/10.1016/j.energy.2020.119562.
     related factors aﬀecting electricity consumption in domestic buildings, Renew. Sus-           [66] X. Gao, A. Malkawi, A new methodology for building energy performance bench-
     tain. Energy Rev. 43 (2015) 901–917, https://doi.org/10.1016/j.rser.2014.11.084.                   marking: an approach based on intelligent clustering algorithm, Energy Build. 84
[42] Y. Yohanis, J. Mondol, A. Wright, B. Norton, Real-life energy use in the UK: how                   (2014) 607–616, https://doi.org/10.1016/j.enbuild.2014.08.030.
     occupancy and dwelling characteristics aﬀect domestic electricity use, Energy Build.          [67] C. Barber, D. Dobkin, H. Huhdanpaa, The quickhull algorithm for convex hulls, ACM
     (2008) 1053–1059, https://doi.org/10.1016/j.enbuild.2007.09.001.                                   Trans. Math. Softw. 22 (1996) 469–483.
[43] F. Fuerst, D. Kavarnou, R. Singh, H. Adan, Determinants of energy consumption and             [68] Google, Google street view, https://www.google.com/streetview/. (Accessed 19
     exposure to energy price risk: a UK study, Z. Immobilienökonomie (2020) 65–80,                     June 2023), 2023.
     https://doi.org/10.1365/s41056-019-00027-y.                                                   [69] F. Johari, F. Shadram, J. Widén, Urban building energy modelling from geo-
[44] R. Räty, A. Carlsson-Kanyama, Comparing energy use by gender, age and income in                    referenced energy performance certiﬁcate data: development, calibration, and vali-
     some European countries, Technical Report, FOI Swedish, Defence Research Agency,                   dation, Sustain. Cities Soc. 96 (2023) 104664, https://doi.org/10.1016/j.scs.2023.
     2009.                                                                                              104664.
[45] J. von Platten, M. Mangold, K. Mjörnell, Energy inequality as a risk in socio-                [70] E. Barbour, C. Cerezo Davila, S. Gupta, C. Reinhart, J. Kaur, M. González, Planning
     technical energy transitions: the Swedish case of individual metering and billing of               for sustainable cities by estimating building occupancy with mobile phones, Nat.
     energy for heating, IOP Conf. Ser. Earth Environ. Sci. 588 (2020) 032015, https://                 Commun. (2019), https://doi.org/10.1038/s41467-019-11685-w.
     doi.org/10.1088/1755-1315/588/3/032015.                                                       [71] M. Pogson, P. Smith, Eﬀect of spatial data resolution on uncertainty, Environ. Model.
[46] K. Gram-Hanssen, Households’ energy use – which is the more important: eﬃcient                     Softw. 63 (2015) 87–96, https://doi.org/10.1016/j.envsoft.2014.09.021.
     technologies or user practices?, in: World Renewable Energy Congress 2011, 2011.              [72] O.G. Consortium, Citygml, https://www.ogc.org/standard/CityGML/. (Accessed 26
[47] J. von Platten, M. Mangold, K. Mjörnell, A matter of metrics? How analysing per                    September 2023), 2023.
     capita energy use changes the face of energy eﬃcient housing in Sweden and reveals            [73] Openstreetmap, OpenStreetMap, https://www.openstreetmap.org/. (Accessed 26
     injustices in the energy transition, Energy Res. Soc. Sci. (2020), https://doi.org/10.             September 2023), 2023.
     1016/j.erss.2020.101807.                                                                      [74] M. Ferrando, F. Causone, T. Hong, Y. Chen, Urban building energy modelling (ubem)
[48] A. Otsuka, Population agglomeration and residential energy consumption: evidence                   tools: a state-of-the-art review of bottom-up physics-based approaches, Sustain.
     from Japan, Sustainability 10 (2018), https://www.mdpi.com/2071-1050/10/2/                         Cities Soc. 62 (2020) 102408, https://doi.org/10.1016/j.scs.2020.102408.
     469.




                                                                                              18
