import random
import math
import statistics

import numpy as np

import dbStuff
import rankingFromPairwise
import utilities
from utilities import powerset
from plotStuff import plot_curves, plot_curves_with_error_bars
from dbStuff import execute_query, connect_to_db, close_connection, getSample, emptyGB
from statStuff import welch_ttest, permutation_test, compute_skewness, compute_kendall_tau, benjamini_hochberg, \
    benjamini_hochberg_statmod, claireStat
import time
from rankingFromPairwise import computeRanksForAll, merge_sort

from statsmodels.stats.multitest import fdrcorrection


import configparser
import json

import bernstein



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





# returns the rank of value in ranking
# returns 0 if value not found
def getRank(value, ranking):
    for r in ranking:
        if r[0] == value:
            rank=r[1]
    return rank


"""
q = ("SELECT " + strgb + "," + sel + "," + meas + ", "
         + " rank () over ( partition by " + strgb + " order by " + meas + " desc ) as rank" +
         #" FROM " + table +
     " FROM \"" + strgb + "\"" +
        " WHERE " + sel + " in " + str(valsToSelect) + " group by " + strgb + "," + sel + " ")
queryHyp = (
        "select * from (select  " + strgb + " from  " + table + ") t1  cross join (values " + hyp + ") as t2 ")
queryExcept = ("select " + strgb + "," + sel + ", rank from  (" + q + " ) t3 except all " + queryHyp + " ")
queryCountExcept = ("select count(*) from (" + queryExcept + ") t5;")
"""

def generateAllqueries(pwrset, sel, meas, function, table, valsToSelect, hypo, mvnames):
    pset=pwrset
    n=len(pwrset)
    tabQuery=[]
    tabCount=[]
    tabCuboid=[]
    hyp = ""
    for i in range(len(hypo)):
        hyp = hyp + str(hypo[i])
        if i != len(hypo) - 1:
            hyp = hyp + ","
    for i in range(n):
        nb = random.randint(0, len(pwrset) - 1)
        gb = pset[nb]
        # without replacement: gb is removed from the list so as not to be drawn twice
        pset.remove(gb)
        strgb = ""
        gbwithoutsel=""
        for i in range(len(gb)):
            strgb = strgb + str(gb[i])
            if i != len(gb) - 1:
                strgb = strgb + ","
        for i in range(len(gb)-1):
            gbwithoutsel = gbwithoutsel + str(gb[i])
            if i != len(gb) - 2:
                gbwithoutsel = gbwithoutsel + ","
        materialized = findMV(mvnames, strgb, table)
        #print(materialized)
        if strgb == sel:
            q = ("SELECT " + strgb + ", " + function + '(' + meas + "), "
                 + " rank () over ( " + gbwithoutsel + " order by " + function + '(' + meas + ") desc ) as rank" +
                 # " FROM " + table +
                 " FROM \"" + str(materialized) + "\"" +
                 " WHERE " + sel + " in " + str(valsToSelect) + " group by " + strgb + " ")
        else:
            q = ("SELECT " + strgb + ", " + function + '(' + meas + "), "
                 + " rank () over ( partition by " + gbwithoutsel + " order by " + function + '(' + meas + ") desc ) as rank" +
                 #" FROM " + table +
             " FROM \"" + str(materialized) + "\"" +
                " WHERE " + sel + " in " + str(valsToSelect) + " group by " + strgb + " ")
        queryHyp = (
                "select " + sel + ",rank  from (values " + hyp + ") as t2 (" + sel + ",rank)")
        queryExcept = ("select * from  (" + q + " ) t3 , (" + queryHyp + ") t4 where t3." + sel + "=t4." + sel + " and t3.rank!=t4.rank")
        queryCountCuboid= ("select count(*) from (" + q + ") t5;")
        queryCountExcept = ("select count(*) from (" + queryExcept + ") t6;")


        tabQuery.append(queryCountExcept)
        tabCount.append(queryCountCuboid)
        tabCuboid.append(strgb)
    return tabQuery,tabCount,tabCuboid

