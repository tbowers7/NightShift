# -*- coding: utf-8 -*-
#
#  This Source Code Form is subject to the terms of the Mozilla Public
#  License, v. 2.0. If a copy of the MPL was not distributed with this
#  file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
#  Created on 16 Nov 2018
#
#  @author: rhamilton

"""Actually plot the GOES-16 data.
"""

from __future__ import division, print_function, absolute_import

import glob

import os
from datetime import datetime as dt

import numpy as np
import pyresample as pr
from netCDF4 import Dataset

from matplotlib import cm
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import ListedColormap

from .. import common as com


def readNC(filename):
    """
    """
    print("Reading: %s" % (filename))
    dat = Dataset(filename)

    return dat


def G16_ABI_L2_ProjDef(nc):
    """
    """
    # The key is that the GOES-16 data are in a geostationary projection
    #   and those details are available in:
    #     dat.variables['goes_imager_projection']
    # See also:
    #     https://proj4.org/operations/projections/geos.html
    proj_var = nc.variables['goes_imager_projection']
    # print(proj_var)

    # Since scanning_angle (radians) = projection_coordinate / h,
    #   the projection coordinates are now easy to get.
    satH = proj_var.perspective_point_height
    satLat = proj_var.latitude_of_projection_origin
    satLon = proj_var.longitude_of_projection_origin
    satSweep = proj_var.sweep_angle_axis
    semi_major = proj_var.semi_major_axis
    semi_minor = proj_var.semi_minor_axis

    x = (nc.variables['x'][:])*satH
    y = (nc.variables['y'][:])*satH

    nx = len(x)
    ny = len(y)

    min_x = x.min()
    max_x = x.max()
    min_y = y.min()
    max_y = y.max()

    # NOTE:
    #   Currently don't know why the google example offsets by half_x/y...
    half_x = (max_x - min_x) / nx / 2.
    half_y = (max_y - min_y) / ny / 2.
    extents = (min_x - half_x, min_y - half_y, max_x + half_x, max_y + half_y)

    # Props to
    #   https://groups.google.com/forum/#!topic/pytroll/EIl0voQDqiI
    # for pointing out that 'sweep' definition is important!!!
    # You get an X & Y offset without it, which makes sense in retrospect.
    old_grid = pr.geometry.AreaDefinition('geos', 'goes_conus', 'geos',
                                          {'proj': 'geos',
                                           'h': str(satH),
                                           'lon_0': str(satLon),
                                           'lat_0': str(satLat),
                                           'a': str(semi_major),
                                           'b': str(semi_minor),
                                           'units': 'm',
                                           'ellps': 'GRS80',
                                           'sweep': satSweep},
                                          nx, ny, extents)

    return old_grid


def crop_image(nc, data, clat, clon, pCoeff=None):
    # Parse/grab the existing projection information
    old_grid = G16_ABI_L2_ProjDef(nc)

    latMin, latMax, lonMin, lonMax = com.maps.set_plot_extent(clat, clon,
                                                              fudge=0.093)

    # Create a grid at at the specified resolution; original default was
    #   0.005 degrees or 18 arcseconds resolution, though I don't remember why
    gridRes = 18./60./60.
    lats = np.arange(latMin, latMax, gridRes)
    lons = np.arange(lonMin, lonMax, gridRes)
    lons, lats = np.meshgrid(lons, lats)

    swath_def = pr.geometry.SwathDefinition(lons=lons, lats=lats)

    # LCC is Lambert conformal conic projection
    area_def = swath_def.compute_optimal_bb_area({'proj': 'lcc',
                                                  'lon_0': clon,
                                                  'lat_0': clat,
                                                  'lat_1': clat,
                                                  'lat_2': clat})

    # If we don't have projection coefficients already, calculate 'em!
    if pCoeff is None:
        # SC2000 FTW
        print("Reticulating splines...")

        # NOTE: On 20181120, when nprocs > 1 it never returned. Bug? Dunno.
        # pCoeff: valid_input_index, valid_output_index,
        #         index_array, distance_array
        pCoeff = pr.kd_tree.get_neighbour_info(old_grid, area_def, 5000.,
                                               neighbours=1, epsilon=0.,
                                               nprocs=1)
        # print('Old projection information: {}'.format(old_grid))
    else:
        # NOTE: I'm not rechecking anything, I'm just assuming it's all good
        #   and reusing it.  It'll probably look messed up in some obvious
        #   way if that ever becomes a problem.
        print("Reusing transformation coefficients!")

    # Now that we're guaranteed to have the projection details, actually do it
    pData = pr.kd_tree.get_sample_from_neighbour_info('nn',
                                                      area_def.shape,
                                                      data,
                                                      pCoeff[0],
                                                      pCoeff[1],
                                                      pCoeff[2])

    # OLD WAY THAT STILL WORKS! Resamples in one step, and its basically just
    #   a wrapper for the above two-step dance.
    # pData = pr.kd_tree.resample_nearest(old_grid, data, area_def,
    #                                     radius_of_influence=5000)

    return old_grid, area_def, pData, pCoeff


def getCMap(vmin=160, vmax=330, trans=None):
    rnge = vmax - vmin
    # NOTE: All values are in Kelvin
    #   trans must be between vmin and vmax!
    if trans is None:
        c01t = 195
        c12t = 255
        c23t = 300

        c0p = int(np.floor(100*((c01t - vmin)/rnge)))
        c1p = int(np.floor(100*(c12t - c01t)/rnge))
        c2p = int(np.floor(100*(c23t - c12t)/rnge))
        c3p = 100 - (c0p + c1p + c2p)

    # Keeping things to a total of 256 for rounding purposes;
    #    If vmin == 330 and vmax == 160

    # Second option is number of entries in the map (lut)
    #   NOTE: twilight_shifted is only in matplotlib ver. >= 3.0!!!!!
    c0 = cm.get_cmap("twilight_shifted", 256)
    # c1 = cm.get_cmap("gist_earth", 80)
    c1 = cm.get_cmap("rainbow_r", 256)
    c2 = cm.get_cmap("bone_r", 256)
    c3 = cm.get_cmap("bone", 256)

    newcolors = np.vstack((c0(np.linspace(0, 1, c0p)),
                           c1(np.linspace(0, 1, c1p)),
                           c2(np.linspace(0, 1, c2p)),
                           c3(np.linspace(0, 1, c3p))))

    newcmp = ListedColormap(newcolors, name='G16_Custom')

    return newcmp


def makePlots(inloc, outloc, mapCenter, roads=None, counties=None,
              cmap=None, forceRegen=False):

    # Warning, you may explode
    #  https://matplotlib.org/api/pyplot_api.html#matplotlib.pyplot.switch_backend
    plt.switch_backend("Agg")

    cLon = mapCenter[0]
    cLat = mapCenter[1]

    flist = sorted(glob.glob(inloc + "*.nc"))

    if cmap is None:
        # Construct/grab the color map.
        #   Purposefully leaving this hardcoded here for now, because it's
        #   so easy to make a god damn mess of the colormap if you don't know
        #   what you're doing.
        cmap = getCMap(vmin=160., vmax=330.)

    # i is the number-of-images processed counter
    i = 0
    for each in flist:
        outpname = "%s/%s.png" % (outloc, os.path.basename(each))

        # Logic to skip stuff already completed, or just redo everything
        if forceRegen is True:
            save = True
        else:
            # Check to see if we're already done with this image
            found = os.path.isfile(outpname)

            if found is True:
                save = False
                print("File %s exists! Skipping." % (outpname))
            else:
                save = True

        if save is True:
            dat = readNC(each)

            # Pull out the channel/band and other identifiers
            chan = dat.variables['band_id'][0]
            plat = "%s (%s)" % (dat.orbital_slot, dat.platform_ID)
            dprod = dat.title

            # Pull out the time stamp
            tend = dt.strptime(dat.time_coverage_end,
                               "%Y-%m-%dT%H:%M:%S.%fZ")

            # If it's our first time through, we definitely need to recalculate
            #   the projection/transformation stuff
            if i == 0:
                pCoeff = None
            else:
                # Check to see if we've rolled over in day, and if so,
                #   force recalculation of the transformation/projection stuff
                if tend.day != tprev.day:
                    pCoeff = None

            # Grab just the image data
            img = dat['CMI'][:]

            # This is the function that actually handles the reprojection
            ogrid, ngrid, ndat, pCoeff = crop_image(dat, img, cLat, cLon,
                                                    pCoeff=pCoeff)

            print('Old projection information: {}'.format(ogrid))
            print('NEW projection information: {}'.format(ngrid))

            # Get the new projection/transformation info for the plot axes
            crs = ngrid.to_cartopy_crs()

            # Get the proper plot extents so we have no whitespace
            print(crs.bounds)
            prlon = (crs.x_limits[1] - crs.x_limits[0])
            prlat = (crs.y_limits[1] - crs.y_limits[0])
            # Ultimate image width/height
            paspect = prlon/prlat

            # !!! WARNING !!!
            #   I hate this kludge, but it works if you let the aspect stretch
            #   just a tiny bit. Necessary for the MP4 creation because the
            #   compression algorithm needs an even number divisor
            figsize = (7., np.round(7./paspect, decimals=2))

            print(prlon, prlat, paspect)
            print(figsize)

            # Figure creation
            fig = plt.figure(figsize=figsize, dpi=100)

            # Needed to remove any whitespace/padding around the imshow()
            plt.subplots_adjust(left=0., right=1., top=1., bottom=0.)

            # Tell matplotlib we're using a map projection so cartopy
            #   takes over and overloades Axes() with GeoAxes()
            ax = plt.axes(projection=crs)

            # This actually sets the background map color so it's darker
            #   when there's no data or missing data.
            ax.background_patch.set_facecolor('#262629')

            # Some custom stuff
            ax = com.maps.add_map_features(ax, counties=counties, roads=roads)
            ax = com.maps.add_AZObs(ax)

            plt.imshow(ndat, transform=crs, extent=crs.bounds, origin='upper',
                       vmin=160., vmax=330., interpolation='none',
                       cmap=cmap)
            # plt.colorbar()

            # Add the informational bar at the top, using info directly
            #   from the original datafiles that we opened at the top
            line1 = "%s  %s" % (plat, dprod)
            line1 = line1.upper()

            # We don't need microseconds shown on this plot
            tendstr = tend.strftime("%Y-%m-%d  %H:%M:%SZ")
            line2 = "Band %02d  %s" % (chan, tendstr)
            line2 = line2.upper()

            # Black background for top label text
            #   NOTE: Z order is important! Text should be higher than trect
            trect = mpatches.Rectangle((0.0, 0.955), width=1.0, height=0.045,
                                       edgecolor=None, facecolor='black',
                                       fill=True, alpha=1.0, zorder=100,
                                       transform=ax.transAxes)
            ax.add_patch(trect)

            # Line 1
            plt.annotate(line1, (0.5, 0.985), xycoords='axes fraction',
                         fontfamily='monospace',
                         horizontalalignment='center',
                         verticalalignment='center',
                         color='white', fontweight='bold', zorder=200)
            # Line 2
            plt.annotate(line2, (0.5, 0.965), xycoords='axes fraction',
                         fontfamily='monospace',
                         horizontalalignment='center',
                         verticalalignment='center',
                         color='white', fontweight='bold', zorder=200)

            # Useful for testing getCmap changes
            # plt.colorbar()

            plt.savefig(outpname, dpi=100)
            print("Saved as %s." % (outpname))
            plt.close()

            # Make sure to save the current timestamp for comparison the
            #   next time through the loop!
            tprev = tend
            i += 1

    return i
