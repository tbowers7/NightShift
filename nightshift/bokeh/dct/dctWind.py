# -*- coding: utf-8 -*-
#
#  This Source Code Form is subject to the terms of the Mozilla Public
#  License, v. 2.0. If a copy of the MPL was not distributed with this
#  file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
#  Created on 6 May 2019
#
#  @author: rhamilton

"""One line description of module.

Further description.
"""

from __future__ import division, print_function, absolute_import

import datetime as dt
from collections import OrderedDict

from ..plotting import helpers
from ..plotting import lineplots as lplot


def dataGatherer(m, qdata, timeFilter=None, fillNull=True, debug=True):
    """
    Instrument/plot/query specific contortions needed to make the
    bulk of the plot code generic and abstract.  I feel ok
    hardcoding stuff in here at least, since this will always be namespace
    protected and unambigious (e.g. instrumentTelem.dataGatherer).
    """
    pdata = OrderedDict()
    for qtag in m.queries.keys():
        pdata.update({qtag: qdata[qtag]})

    # Get the keys that define the input dataset
    r = pdata['q_dctweather']

    # Get rid of series that won't be appearing in this plot
    r = r.drop("AirTemp", axis=1)
    r = r.drop("Humidity", axis=1)
    r = r.drop("DewPoint", axis=1)

    # For now, I'm ignoring the wind direction information. Will revisit.
    r = r.drop("WindDir2MinAvg", axis=1)

    # Adjust the units from mph to m/s
    #   Decided to be super pedantic and break it down to the fundamental
    #   definition of 1 inch == 2.54 cm.  Silly, I know.  Whatever.
    imperialToMetric = (63360./(60.*60.))*(0.0254)
    r.WindSpeed2MinAvg = r.WindSpeed2MinAvg * imperialToMetric
    r.WindSpeed60MinMax = r.WindSpeed60MinMax * imperialToMetric

    if timeFilter is None:
        rj = r
        if fillNull is True:
            # Make sure that we don't have too awkward of a dataframe
            #   by filling gaps. This has the benefit of making the
            #   tooltip patches WAY easier to handle.
            rj.fillna(method='ffill', inplace=True)
    else:
        # Now select only the data in those frames since lastTime
        #   But! Of course there's another caveat.
        # lastTimedt could be a dt.datetime object, but r.index has a type of
        #   Timestamp which is really a np.datetime64 wrapper. So we need
        #   to put them on the same page for actual comparisons.
        # NOTE: The logic here was unrolled for debugging timestamp crap.
        #   it can be rolled up again in the next version.
        ripydt = r.index.to_pydatetime()

        if debug is True:
            print("Last in CDS: %s" % (timeFilter))
            print("Last in r  : %s" % (ripydt[-1]))

        rTimeSearchMask = ripydt > timeFilter

        # Need .loc since we're really filtering by label
        rj = r.loc[rTimeSearchMask]

    return rj


def make_plot(doc):
    """
    This is called every time someone visits a pre-defined endpoint;
    see the apps dict in the main calling code for what that actualls is.
    """
    # Grab our stashed information from the template
    plotState = doc.template.globals['plotState']

    mods = plotState.modules
    qdata = plotState.data
    dset = plotState.colors
    theme = plotState.theme

    #
    # NOTE: Should clean this up or stuff it all into dataGatherer
    #
    # Hard coding the access/dict key for the data needed for this plot
    #   Cringe-worthy but tolerable. This MUST match what is set in the
    #   'modules.conf' file otherwise it'll blow up.
    moduleKey = 'weather_TempHumi'
    m = mods[moduleKey]

    print("Serving %s" % (m.title))

    # Use this to consistently filter/gather the data based on some
    #   specific tags/reorganizing
    r = dataGatherer(m, qdata)

    # A dict of helpful plot labels
    ldict = {'title': "DCT Weather Information",
             'xlabel': "Time (UTC)",
             'y1label': "Wind Speed (m/s)"}

    # Since we haven't plotted anything yet, we don't have a decent idea
    #   of the bounds that we make our patches over. So just do that manually.
    # Remember that .min and .max are methods! Need the ()
    #   Also adjust plot extents to pad +/- N percent
    npad = 0.1
    y1lim = None
    if y1lim is None:
        # The minimum wind speed is always 0 :)
        y1lim = [0,
                 r.WindSpeed60MinMax.max(skipna=True)]

        # Now pad them appropriately, checking for a negative limit
        if y1lim[0] < 0:
            y1lim[0] *= (1.+npad)
        else:
            y1lim[0] *= (1.-npad)

        if y1lim[1] < 0:
            y1lim[1] *= (1.-npad)
        else:
            y1lim[1] *= (1.+npad)

    # This does everything else. Loops over the columns in the 'r' DataFrame
    #   and creates a ColumnDataSource for the resulting figure
    fig, cds, cols = lplot.commonPlot(r, ldict, y1lim, dset,
                                      height=400, width=500)

    sunrise, sunset = lplot.createSunAnnotations(qdata)
    fig.add_layout(sunrise)
    fig.add_layout(sunset)

    # At this point, we're done! Just apply the theme and attach the figure
    #   to the rest of the document, then setup the update callback
    doc.theme = theme
    doc.title = m.title
    doc.add_root(fig)

    def grabNew():
        print("Checking for new data!")

        # Check our stash
        qdata = doc.template.globals['plotState'].data
        timeUpdate = doc.template.globals['plotState'].timestamp
        tdiff = (dt.datetime.utcnow() - timeUpdate).total_seconds()
        print("Data were updated %f seconds ago (%s)" % (tdiff, timeUpdate))

        # Get the last timestamp present in the existing ColumnDataSource
        lastTime = cds.data['index'].max()

        # Turn it into a datetime.datetime (with UTC timezone)
        lastTimedt = helpers.convertTimestamp(lastTime, tz='UTC')

        # Sweep up all the data, and filter down to only those
        #   after the given time
        nf = dataGatherer(m, qdata, timeFilter=lastTimedt)

        # Check the data for updates, and downselect to just the newest
        mds2 = lplot.newDataCallback(cds, cols, nf, lastTimedt, y1lim)

        # Actually update the data
        if mds2 != {}:
            cds.stream(mds2, rollover=15000)
            print("New data streamed; %d row(s) added" % (nf.shape[0]))

        # Check to see if we have to update the sunrise/sunset times
        #   Create new ones so it's super easy to just compare by .location
        nsunrise, nsunset = lplot.createSunAnnotations(qdata)

        # Check to see if there's actually an update
        if sunrise.location != nsunrise.location:
            print("Updated sunrise span location")
            sunrise.location = sunrise.location

        if sunset.location != nsunset.location:
            print("Updated sunset span location")
            sunset.location = nsunset.location

        print()

    print("")

    doc.add_periodic_callback(grabNew, 5000)

    return doc
