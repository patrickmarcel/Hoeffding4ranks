import random
import math
import numpy as np

import dbStuff
import rankingFromPairwise
import utilities
from utilities import powerset
from plotStuff import plot_curves
from dbStuff import execute_query, connect_to_db, close_connection, getSample, emptyGB
from statStuff import welch_ttest, permutation_test, compute_skewness, compute_kendall_tau, benjamini_hochberg, \
    benjamini_hochberg_statmod, claireStat
import time
from rankingFromPairwise import computeRanksForAll, merge_sort

from statsmodels.stats.multitest import fdrcorrection


import configparser
import json

import bernstein


# ------  Debug ?  ------------
DEBUG_FLAG = True


def get_state_sample(conn, measBase, table, sel, sampleSize, state):

    querySample = "SELECT "+sel+", "+measBase+" FROM "+table+" where "+sel+" = '"+str(state)+"' limit "+str(sampleSize)+";"
    #print(querySample)
    resultVals = execute_query(conn, querySample)
    return resultVals

def generateRandomQuery(pwsert, valsToSelect, hypothesis):
    nb = random.randint(0, len(pwsert) - 1)
    gb = pwsert[nb]
    strgb = ""
    for i in range(len(gb)):
        strgb = strgb + str(gb[i])
        if i != len(gb) - 1:
            strgb = strgb + ","

    print("group by is: " + strgb)

    # for debugging
    # strgb = "departure_airport"

    #print("vals in gen queries:", valsToSelect)
    hyp = ""
    for i in range(len(hypothesis)):
        hyp = hyp + str(hypothesis[i])
        if i != len(hypothesis) - 1:
            hyp = hyp + ","
    queryHyp = (
            "select * from (select  " + strgb + " from  " + table + ") t1  cross join (values " + hyp + ") as t2 ")

    query = ("SELECT " + strgb + "," + sel + "," + meas + ", "
             + " rank () over ( partition by " + strgb + " order by " + meas + " desc ) as rank" +
             " FROM " + table + " WHERE " + sel + " in " + str(valsToSelect) + " group by " + strgb + "," + sel + " ")

    queryValues = ("SELECT measure FROM (SELECT " + strgb + "," + sel + "," + meas + " as measure FROM "
                   + table + " WHERE " + sel + " in " + str(valsToSelect) + " group by " + strgb + "," + sel + " ) x;")

    queryExcept = ("select " + strgb + "," + sel + ", rank from  (" + query + " ) t3 except all " + queryHyp + " ")

    queryCountGb = ("select count(*) from (" + queryHyp + ") t4;")
    queryCountExcept = ("select count(*) from (" + queryExcept + ") t5;")

    #return query, queryHyp, queryValues, queryExcept, strgb
    return queryValues, queryCountGb, queryCountExcept


def getValues(queryValues, vals, v, conn):
    queryVal = queryValues.replace(str(vals), "('" + v + "')")
    resultValues = execute_query(conn, queryVal)
    data = []
    for row in resultValues:
        data.append(float(row[0]))

    np.array(data)
    return data


def computeBHcorrection(pairwiseComparison, alpha=0.05):
    # rejected, corrected_p_values = benjamini_hochberg_gpt(tabPValues, alpha)
    # print("Rejected hypotheses:", rejected)
    # print("raw p-values:", tabPValues)
    # print("Corrected p-values (gpt):", corrected_p_values)
    tabPValues = []
    for p in pairwiseComparison:
        tabPValues.append(p[4])

    corrected = benjamini_hochberg(tabPValues, alpha)
    rejected, corrected2 = benjamini_hochberg_statmod(tabPValues, alpha)

    print("nb of True in rejected: ", utilities.nbTrueInList(rejected))

    pairwiseComp2 = []
    i = 0
    nbChanges = 0
    for c in pairwiseComparison:
        comp = 0  # not significant
        if corrected[i] < 0.05 and c[3] < 0:
            comp = -1
        if corrected[i] < 0.05 and c[3] > 0:
            comp = 1
        if comp != c[2]:
            nbChanges = nbChanges + 1
        pairwiseComp2.append((c[0], c[1], comp, c[2], corrected[i]))
        i = i + 1

    print("Number of BH corrections: ", nbChanges)

    print("nb non zeros after corrections: ", utilities.countNonZeros(pairwiseComp2))

    return pairwiseComp2


def generateComparisonsWithMergeSort(Sels, S):
    # compute Claire statistics for all pairs
    claireTab = []
    for i in range(1, len(S)):
        for j in range(i, len(S)):
            b = claireStat(S[i - 1][2], S[j][2], S[i - 1][1], S[j][1])
            claireTab.append((S[i - 1][0], S[j][0], b, S[i - 1][3], S[j][3]))

    #claireComp = [(x[0],x[1],x[2]) for x in claireTab]
    #print("claireComp: ", claireTab)
    print("merge: ", merge_sort(Sels, claireTab))
    print("pairwise: ", rankingFromPairwise.pairwiseComparison)

    return rankingFromPairwise.pairwiseComparison


def generateAllComparisons(Sels, S, nbOfComparisons):
    #tabPValues = []
    pairwiseComparison = []
    #tabStat = []

    # compute Claire statistics for all pairs
    claireTab = []
    for i in range(1, len(S)):
        for j in range(i, len(S)):
            b = claireStat(S[i - 1][2], S[j][2], S[i - 1][1], S[j][1])
            claireTab.append((S[i - 1][0], S[j][0], b, S[i - 1][3], S[j][3]))

            if b:
                # print("Welch test can be used")
                t_stat, p_value, conclusion = welch_ttest(S[i - 1][3], S[j][3])
                # print(t_stat, p_value, conclusion)
                #tabStat.append(t_stat)
                #tabPValues.append(float(p_value))
                comp = 0  # not significant
                if p_value < 0.05 and t_stat < 0:
                    comp = -1
                if p_value < 0.05 and t_stat > 0:
                    comp = 1
                pairwiseComparison.append((S[i - 1][0], S[j][0], comp, t_stat, float(p_value)))
            else:
                # print("Permutation test is used")
                observed_t_stat, p_value, permuted_t_stats, conclusion = permutation_test(S[i - 1][3], S[j][3])
                # print(f"Observed Welch's t-statistic: {observed_t_stat}")
                # print(f"P-value: {p_value}")
                # print(f"conclusion: {conclusion}")
                # print(observed_t_stat, p_value, conclusion)
                #tabStat.append(observed_t_stat)
                #tabPValues.append(float(p_value))
                comp = 0  # not significant
                if p_value < 0.05 and observed_t_stat < 0:
                    comp = -1
                if p_value < 0.05 and observed_t_stat > 0:
                    comp = 1
                pairwiseComparison.append((S[i - 1][0], S[j][0], comp, observed_t_stat, float(p_value)))

    pairwiseComparison = computeBHcorrection(pairwiseComparison, 0.05)
    return pairwiseComparison


def generateHypothesisTest(conn, meas, measBase, table, sel, sampleSize, method):
    resultVals = getSample(conn, measBase, table, sel, sampleSize, method=method, repeatable=False)
    #resultVals = getSample(conn, measBase, table, sel, sampleSize, method=method, repeatable=DEBUG_FLAG)

    # get adom values
    Sels = list(set([x[0] for x in resultVals]))

    #analyse sample for each adom value: value, nb of measures, skewness, and tuples
    S = []
    for v in Sels:

        data = []
        for row in resultVals:
            if row[0] == v:
                data.append(float(row[1]))

        nvalues = len(data)
        data = np.array(data)
        skewness = compute_skewness(data)
        S.append((v, nvalues, skewness, data))

    #print(S)

    # nlog(n) comparisons enough for recovering the true ranking when commarisons are certain (not noisy)
    # we should try less
    nbOfComparisons = len(Sels) * math.log(len(Sels), 2)
    #print("Number of comparisons to make: " + str(nbOfComparisons))

    pairwiseComparison=generateAllComparisons(Sels, S, nbOfComparisons)

    #for p in pairwiseComparison:
    #    print("p: ", p)

    #pairwiseComparison = generateComparisonsWithMergeSort(Sels, S)

    # ranking
    #ranks = balanced_rank_estimation(pairwiseComparison)
    #print("Balanced Rank Estimation:", ranks)
    ranks = computeRanksForAll(pairwiseComparison, Sels)

    sorted_items = sorted(ranks.items(), key=lambda item: item[1], reverse=True)

    # Construct a rank from the number of comparison won for each adom values
    hypothesis = []
    rank = 0
    for s in sorted_items:
        if rank == 0:
            rank = 1
            hypothesis.append((s[0], rank))
            val = s[1]
        else:
            if s[1] == val:
                hypothesis.append((s[0], rank))
                val = s[1]
            else:
                rank = rank + 1
                hypothesis.append((s[0], rank))
                val = s[1]

    return hypothesis

#This function estimates the number of violations in all the cube of R
#by randomly drawing tuples from the materialized cuboids (R included)
#It uses Hoeffding concentration inequality for bounding the number of draws according to a confidence interval
def estimateViolations(conn, meas, measBase, table, sel, cuboids, ranking, epsilon = 0.1, alpha = 0.1):
    #n is number of draws
    n = math.log(2 / alpha, 10) / (2 * epsilon * epsilon)
    n = math.ceil(n)

    estimates=0

    for i in range(n):
        nCuboid = random.randint(1, len(cuboids)) #+1 is for R itself
        print("nCuboid: ",nCuboid)
        #if nCuboid == len(cuboids):
        #    #draw in R
        #    #TODO draw tuples where only diff is on sel attribute!
        #    tuples=getSample(conn, measBase, table, sel, 5)
        #else:
        #draw in cuboid nCuboid
        view=cuboids[nCuboid][0]
        tuples=getSample(conn, "avg", view, sel, 5)
        if checkViolation(tuples, ranking) == True:
            estimates=estimates+1

    return n, estimates

# returns the rank of value in ranking
# returns 0 if value not found
def getRank(value, ranking):
    for r in ranking:
        if r[0] == value:
            rank=r[1]
    return rank

#checks if tuples violate ranking, return True if this is the case
def checkViolation(tuples, ranking):
    print("tuples: ", tuples)
    print("ranking: ", ranking)

    meast1 = tuples[0][1]
    meast2 = tuples[1][1]

    valuet1 = tuples[0][0]
    valuet2 = tuples[1][0]

    rankt1 = getRank(valuet1,ranking)
    rankt2 = getRank(valuet2, ranking)

    if meast1<meast2 and rankt1<rankt2:
        return True
    else:
        return False

def hoeffdingForRank(groupbyAtt, n, valsToSelect, limitedHyp):
    print("Size of confidence interval around p: " + str(epsilon))
    print("Probability is of making a mistake: " + str(alpha))

    # n queries enough according to Hoeffding
    print("n: " + str(n))

    # compute powerset of categorical attributes
    pwset = powerset(groupbyAtt)

    # empty group by set removed from powerset
    # since it WAS used to generate the hypothesis

    pwset.remove(())

    #print("Hypothesis is:" + str(hypothesis))

    nbTests = 0
    for i in range(n):

        # generate the random query
        # query, queryHyp, queryValues, queryExcept, strgb = generateRandomQuery(pwsert,hypothesis)
        queryValues, queryCountGb, queryCountExcept = generateRandomQuery(pwset, valsToSelect, limitedHyp)

        # strategy: use the db engine to check whether the hypothesis holds
        # cross join hypothesis to chosen group by set
        # compute the actual ranks of vals in the hypothesis for each group
        # except all the actual ranks with the hypothesis
        # remaining only the groups where hypothesis does not hold

        resultCountGb = execute_query(conn, queryCountGb)
        resultCountExcept = execute_query(conn, queryCountExcept)

        print("number of tuples checked: " + str(resultCountGb[0][0]))
        print("number of exceptions: " + str(resultCountExcept[0][0]))
        print("ratio is: " + str(resultCountExcept[0][0] / resultCountGb[0][0]))

        ratio = resultCountExcept[0][0] / resultCountGb[0][0]

        # keep actual ratio
        # could use Bernouilli random variables instead: 1 if less than 10% errors
        if ratio > threshold:
            H.append(ratio)
        #    H.append(0)
        else:
            H.append(ratio)
        #    H.append(1)

        #nbTests = nbTests + 1

    expectedValue = sum(H) / len(H)
    print("Expected value is: " + str(sum(H) / len(H)))
    return expectedValue

# returns true if tuple violates ranking
# TODO check!
def countViolations(conn, viewName, ranking):
    viewDef=dbStuff.getDefOfMV(conn, viewName)
    strgb=viewDef.split("GROUP BY ")[1].split(";")[0]
    queryHyp = (
            "select * from (select  * from " + viewName +  ") t1  cross join (values " + ranking + ") as t2 ")

    query = ("SELECT " + strgb + "," + sel + "," + meas + ", "
             + " rank () over ( partition by " + strgb + " order by " + meas + " desc ) as rank" +
             " FROM " + table +  " group by " + strgb + "," + sel + " ")

    #queryValues = ("SELECT measure FROM (SELECT " + strgb + "," + sel + "," + meas + " as measure FROM "+ table + " WHERE " + sel + " in " + str(valsToSelect) + " group by " + strgb + "," + sel + " ) x;")

    queryExcept = ("select " + strgb + "," + sel + ", rank from  (" + query + " ) t3 except all " + queryHyp + " ")

    #queryCountGb = ("select count(*) from (" + queryHyp + ") t4;")
    queryCountExcept = ("select count(*) from (" + queryExcept + ") t5;")
    return dbStuff.execute_query(conn, queryCountExcept)




#draws n views, return those having less than threshold violations
# TODO check!
def azuma(conn, n, threshold, ranking):
    print(n + " draws, you have "+ (100-n) +"% of chances to get " + math.sqrt(2*n*math.log(n))+ " cuboids with acceptable violations")
    res = dbStuff.getMVnames(conn)
    #print(res)
    for i in range(n):
        nb = random.randint(0, len(res) - 1)
        viewName = res[nb][0]
        print(viewName)
        res.remove(nb)
        view=dbStuff.execute_query(conn, "select * from "+viewName + ";")
        print(view)
        nbViolations=countViolations(view, ranking)
        tabView=[]
        if nbViolations < threshold:
            tabView.append(view)
        return tabView


def fetchCongressionalSample(conn,sel,table,measBase,sampleSize, adom_restr=None):
    # fetch the congressional sample
    if adom_restr:
        adom = adom_restr
    else:
        adom = [x[0] for x in execute_query(conn, "select distinct  " + sel + " from " + table + ";")]
    table_size = execute_query(conn, "select count(1) from " + table + ";")[0][0]

    sample_size = int(table_size * sampleSize)
    alpha = 0.10
    house_size = sample_size * alpha
    senate_size = sample_size * (1 - alpha)

    house = getSample(conn, measBase, table, sel, house_size, method="SYSTEM_ROWS", repeatable=False)

    senate = []
    state_sample_size = int(senate_size / len(adom))
    for state in adom:
        senate.extend(get_state_sample(conn, measBase, table, sel, state_sample_size, state))

    if adom_restr:
        house = list(filter(lambda x: x[0] in adom_restr, house))
    congress = house + senate
    # END - fetch the congressional sample
    return adom, congress,


def getHypothesisCongressionalSampling(adom,congress):

    buckets = {s: [] for s in adom}
    skews = dict()
    for item in congress:
        buckets[item[0]].append(item[1])
    for k in buckets.keys():
        skews[k] = compute_skewness(buckets[k])

    # do all welch tests
    param_budget = 20
    param_budget = int(param_budget / 2)

    from scipy.stats import ttest_ind

    raw_comparisons = []

    for i in range(len(adom)):
        for j in range(i + 1, len(adom)):
            left = adom[i]
            right = adom[j]
            res = ttest_ind(buckets[left], buckets[right], equal_var=False)
            stat_c = claireStat(skews[left], skews[right], len(buckets[left]), len(buckets[right]))
            if res.statistic < 0:
                raw_comparisons.append((left, right, stat_c, res.pvalue ))
            else:
                raw_comparisons.append((right, left, stat_c, res.pvalue ))

    w_comparisons = []
    w_comparisons_rej = []
    print(raw_comparisons)
    rejected, corrected = fdrcorrection([x[3] for x in raw_comparisons], alpha=0.05)
    for i in range(len(raw_comparisons)):
        if rejected[i]:
            w_comparisons_rej.append((raw_comparisons[i][0], raw_comparisons[i][1], raw_comparisons[i][2]))
        else:
            w_comparisons.append((raw_comparisons[i][0], raw_comparisons[i][1], raw_comparisons[i][2]))

    print("NB de comparaisons significatives (welch)", len(w_comparisons))
    # print_comp_list(sorted(w_comparisons, key=lambda x: x[0] + x[1]))
    by_prox_to_threshold = sorted(w_comparisons, key=lambda x: abs(0.05 - x[2]), reverse=True)
    # print(by_prox_to_threshold)

    final = by_prox_to_threshold[param_budget:]
    to_redo = by_prox_to_threshold[:param_budget]

    to_redo.extend(sorted(w_comparisons_rej, key=lambda x: abs(0.05 - x[2]), reverse=True)[:param_budget])

    for left, right, _ in to_redo:
        res = permutation_test(buckets[left], buckets[right])
        if res[3].startswith("Reject"):
            if res[1] > 0:
                final.append((left, right, -1))
            else:
                final.append((right, left, -1))

    print("NB de comparaisons significatives (welch + X param)", len(final))
    # print_comp_list(sorted(final, key=lambda x: x[0] + x[1]))

    # borda hypothesis
    patrick_format = [(a, b, 1, None, None) for (a, b, c) in final]
    hypothesis = computeRanksForAll(patrick_format, adom).items()
    hypothesis = [(a, b + 1) for (a, b) in hypothesis]
    hypothesis = sorted(
        hypothesis,
        key=lambda x: x[1]
    )
    return hypothesis


def test(conn, nbAdomVals, ratioViolations, proba, error, percentOfLattice, groupbyAtt, sel, measBase, function,table,sampleSize,comparison=False,generateIndex=False):
    #sampling
    start_time = time.time()
    adom, congress=fetchCongressionalSample(conn,sel,table,measBase,sampleSize, adom_restr=prefs)
    end_time = time.time()
    samplingTime = end_time - start_time
    print('sampling time:',samplingTime)

    # compute hypothesis
    start_time = time.time()
    hypothesis = getHypothesisCongressionalSampling(adom,congress)
    end_time = time.time()
    hypothesisGenerationTime = end_time - start_time
    print('hypothesis generation time:', hypothesisGenerationTime)

    print("Hypothesis as predicted: ", hypothesis)
    limitedHyp = []
    valsToSelect = []
    j = 0
    for h in hypothesis:
        if (h[1] <= nbAdomVals and j < nbAdomVals):
            limitedHyp.append(h)
            valsToSelect.append(h[0])
            j = j + 1
    print("Hypothesis limited to choosen values: ", limitedHyp)

    # print("vals: ",valsToSelect)

    # just for checking on groupBy sel
    # emptyGBresult, emptyGBresultAll = emptyGB(conn, nbAdomVals, table, sel, meas)
    # print("Empty GB says:", emptyGBresult)
    # valsEmptyGB=[a for (a, b) in emptyGBresult]
    # print(valsEmptyGB)


    # generate and get all materialized cuboids
    dbStuff.dropAllMVs(conn)
    dbStuff.createMV(conn, groupbyAtt, sel, measBase, function, table, percentOfLattice)
    mvnames = dbStuff.getMVnames(conn)

    # generate hash index on sel attribute
    if generateIndex==True:
        dbStuff.generateHashIndex(conn,table,sel)

    #validation of hypothesis
    start_time = time.time()

    sizeofsample = int(bernstein.sizeOfSampleHoeffding(proba, error)) + 1
    print('size of sample according to Hoeffding:', sizeofsample)

    # total number of cuboids
    N = len(utilities.powerset(groupbyAtt))
    print('size of sample according to Bardenet:',
          int(bernstein.sizeOfSampleHoeffdingSerflingFromBardenet(proba, error, N)) + 1)

    pwrset = dbStuff.getCuboidsOfAtt(groupbyAtt, sel)
    print(str(tuple(valsToSelect)))
    queryCountviolations, queryCountCuboid, cuboid = bernstein.getSample(proba, error, pwrset, sel, measBase, function,
                                                                         table, tuple(valsToSelect), limitedHyp,
                                                                         mvnames,False,True)
    # queryCountviolations, queryCountCuboid, cuboid=bernstein.getSample(proba, error, pwrset, sel, measBase, function, table, tuple(valsEmptyGB), emptyGBresult, mvnames)

    tabRandomVar = []
    nbViewOK = 0
    for i in range(len(queryCountviolations)):
        # print(queryCountviolations[i])
        # print(queryCountCuboid[i])
        v = dbStuff.execute_query(conn, queryCountviolations[i])[0][0]
        c = dbStuff.execute_query(conn, queryCountCuboid[i])[0][0]
        # print(v)
        # print(c)
        print(v/c, " violation rate in cuboid ", cuboid[i], " of size: ", c, ". Number of violations: ", v)
        if v / c < ratioViolations:
            tabRandomVar.append(1)
            nbViewOK = nbViewOK + 1
        else:
            tabRandomVar.append(0)

    end_time = time.time()
    validationTime = end_time - start_time
    print('validation time:', validationTime)

    variance = np.var(tabRandomVar)
    # print('variance: ', variance)
    prediction = nbViewOK / sizeofsample
    predictionNbOk = prediction * len(pwrset)
    print('nb of views ok: ', nbViewOK, 'out of ', sizeofsample, 'views, i.e., rate of:', nbViewOK / sizeofsample)
    print('predicting number of views ok:', predictionNbOk)

    nbErrors = 2
    print('probability of making ', nbErrors, ' errors: ', bernstein.bernsteinBound(variance, nbErrors))
    print('the error (according to Bernstein) for sum and confidence interval of size', proba, ' is: ',
          bernstein.bersteinError(proba, variance))
    bennetError=bernstein.bennetErrorOnAvg(proba, variance, sizeofsample)
    print('the error (according to Bennet) for avg and confidence interval of size', proba, ' is: ',
          bernstein.bennetErrorOnAvg(proba, variance, sizeofsample))
    print('the error (empirical bennet) for avg and confidence interval of size', proba, ' is: ',
          bernstein.empiricalBennetFromMaurer(proba, variance, sizeofsample))
    print('the error (according to bardenet) for avg and confidence interval of size', proba, ' is: ',
          bernstein.empiricalBernsteinFromBardenet(proba, variance, sizeofsample, N))



    if comparison==True:
        # comparison with ground truth
        dbStuff.dropAllMVs(conn)
        nbMVs = dbStuff.createMV(conn, groupbyAtt, sel, measBase, function, table, 1)

        queryCountviolations, queryCountCuboid, cuboid = bernstein.generateAllqueries(pwrset, sel, measBase, function,
                                                                                      table, tuple(valsToSelect),
                                                                                      limitedHyp, mvnames)

        tabRandomVar = []
        nbViewOK = 0
        for i in range(len(queryCountviolations)):
            #print(queryCountviolations[i])
            # print(queryCountCuboid[i])
            v = dbStuff.execute_query(conn, queryCountviolations[i])[0][0]
            c = dbStuff.execute_query(conn, queryCountCuboid[i])[0][0]
            # print(v)
            # print(c)
            print(v / c, " violation rate in cuboid ", cuboid[i], " of size: ", c, ". Number of violations: ", v)
            if v / c < ratioViolations:
                tabRandomVar.append(1)
                nbViewOK = nbViewOK + 1
            else:
                tabRandomVar.append(0)

        variance = np.var(tabRandomVar)
        # print('variance: ', variance)
        print('*** comparison to ground truth ***')
        print('nb of views ok: ', nbViewOK, 'out of ', nbMVs, 'views, i.e., rate of:', nbViewOK / nbMVs)
        gtratio= nbViewOK / nbMVs

        realError=abs(prediction - (nbViewOK / nbMVs))
        print('Error on avg is: ', abs(prediction - (nbViewOK / nbMVs)))

        print('Error on sum is: ', abs(nbViewOK - predictionNbOk))

        print('the error (according to Bennet) for avg and confidence interval of size', proba, ' is: ',
              bernstein.bennetErrorOnAvg(proba, variance, sizeofsample))
        print('the error (according to Bernstein) for confidence interval of size', proba, ' is: ',
              bernstein.bersteinError(proba, variance))

        return prediction,bennetError,realError,gtratio
    else:
        return prediction, bennetError, hypothesisGenerationTime, validationTime


# TODO
#
#  change sel and measures
#  use other databases
#

if __name__ == "__main__":

    config = configparser.ConfigParser()

    # The DB wee want
    config.read('configs/ssb.ini')
    # The system this is running on
    USER = "PM"

    # Database connection parameters
    dbname = config[USER]['dbname']
    user = config[USER]['user']
    password = config[USER]['password']
    host = config[USER]['host']
    port = int(config[USER]['port'])

    # Cube info
    table = config["Common"]['table']
    measures = json.loads(config.get("Common", "measures"))
    groupbyAtt = json.loads(config.get("Common", "groupbyAtt"))
    sel = config["Common"]['sel']
    meas = config["Common"]['meas']
    measBase = config["Common"]['measBase']
    function = config["Common"]['function']
    prefs = json.loads(config.get("Common", "preferred"))
    if len(prefs) == 0:
        prefs = None


    # number of values of adom to consider - top ones after hypothesis is generated
    nbAdomVals = 5

    # for Hoeffding
    epsilon = 0.1
    alpha = 0.1
    p = 0
    H = []
    threshold = 0.1  # 10% of tuples violating the order
    n = math.log(2 / alpha, 10) / (2* epsilon * epsilon)
    n = math.ceil(n)

    # for DB sampling
    sampleSize = 0.02
    samplingMethod = 'SYSTEM_ROWS'  # or SYSTEM

    if DEBUG_FLAG:
        nbruns = 1
    else:
        nbruns = 10

    # Connect to the database
    conn = connect_to_db(dbname, user, password, host, port)

    # to always have the same order in group bys, with sel attribute last
    groupbyAtt.sort()

    ratioViolations = 0.4
    ratioCuboidOK = 0.8

    proba = 0.2
    error = 0.4  # rate

    percentOfLattice=0.3

    nbWrongRanking=0
    resultRuns=[]

    # do we compare to ground truth?
    comparison = False

    if comparison==True:
        for percentOfLattice in (0.1, 0.25):
        #for sampleSize in (0.1, 0.25, 0.5, 0.75, 1):
        #for nbAdomVals in range(2,10):

            prediction,bennetError,realError,gtratio=test(conn, nbAdomVals, ratioViolations, proba, error, percentOfLattice, groupbyAtt, sel, measBase, function,table, sampleSize, comparison)
            resultRuns.append((percentOfLattice,prediction,bennetError,realError))
            if gtratio <ratioCuboidOK:
                nbWrongRanking=nbWrongRanking+1

        print('Number of incorrect hypothesis:', nbWrongRanking)
        names = ['prediction', 'bennet', 'error']
        title = 'top-' + str(nbAdomVals)
        plot_curves(resultRuns, names, 'percentoflattice', 'error', title)
    else:
        for percentOfLattice in (0.1, 0.2, 0.3, 0.4, 0.5):
        # for sampleSize in (0.1, 0.25, 0.5, 0.75, 1):
        # for nbAdomVals in range(2,10):

            prediction, bennetError, hypothesisTime, validationTime = test(conn, nbAdomVals, ratioViolations, proba, error,
                                                               percentOfLattice, groupbyAtt, sel, measBase, function,
                                                               table, sampleSize, comparison, generateIndex=True)
            resultRuns.append((percentOfLattice, bennetError, hypothesisTime, validationTime))


        names = ['error', 'hypothesis', 'validation']
        title = 'top-' + str(nbAdomVals)
        plot_curves(resultRuns, names, 'percentoflattice', 'time', title)

    # Close the connection
    close_connection(conn)



