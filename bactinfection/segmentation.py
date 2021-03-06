"""
Class implementing segmentation tools.
"""

# Author: Guillaume Witz, Science IT Support, Bern University, 2019-2020
# License: BSD3

import os
import numpy as np
import pandas as pd
import skimage
import skimage.measure
import skimage.morphology
from skimage.feature import match_template
import napari
import pickle

# import ipywidgets as ipw

from . import utils

# import warnings
# warnings.filterwarnings('ignore')


class Bact:
    def __init__(
        self,
        channels=None,
        all_files=None,
        folder_name=None,
        corr_threshold=0.5,
        min_corr_vol=3,
        use_ml=False,
        use_cellpose=False,
        model=None,
        saveto="Segmented",
    ):

        """Standard __init__ method.

        Parameters
        ----------
        channels : list of str
            list of available channels
        all_files : list of str
            list of files to analyze
        folder_name : str
            path of folder to analyze
        corr_threshold : float
            threshold cross-correlation for template matching
        min_corr_vol : int
            minimal number of voxels in rotational volume matching regions
        use_ml : bool
            use manual annotation and ML for nucleus segmentation
        use_cellpose : bool
            use cellpose for nucleus segmentation
        cellpose_type : str
            type of cellpose model to use for nuclei segmentation:
            either 'nuclei' or 'cyto'
        model : cellpose model
            cellpose model
        saveto : str
            folder name wehre to save the segmentation

        Attributes
        ----------

        nucl_channel: str
            name of nucleus channel
        bact_channel:  str
            name of bacteria channel
        cell_channel:  str
            name of cell channel
        masking : str
            what type of bacteria masking to use:
            'cells', 'nuclei' or 'both'

        """

        self.channels = channels
        self.all_files = all_files
        self.folder_name = folder_name
        self.corr_threshold = corr_threshold
        self.min_corr_vol = min_corr_vol
        self.use_ml = use_ml
        self.use_cellpose = use_cellpose
        self.cellpose_type = "nuclei"
        self.model = model
        self.saveto = saveto

        self.current_image = None
        self.current_image_med = None
        self.hard_threshold = None
        self.maxproj = None
        self.bact_mask = None
        self.ml = None
        self.result = None
        self.nucl_channel = None
        self.bact_channel = None
        self.cell_channel = None
        self.minsize = 0
        self.fillholes = False
        self.cellpose_diam = 60
        self.masking = 'cells'
        self.zoom = 0

    def initialize_output(self):
        """Initialize result variables"""

        self.nuclei_segmentation = {os.path.split(x)[1]: None for x in self.all_files}
        self.bacteria_segmentation = {os.path.split(x)[1]: None for x in self.all_files}
        self.cell_segmentation = {os.path.split(x)[1]: None for x in self.all_files}
        self.actin_segmentation = {os.path.split(x)[1]: None for x in self.all_files}
        self.annotations = {os.path.split(x)[1]: None for x in self.all_files}
        self.bact_measurements = {os.path.split(x)[1]: None for x in self.all_files}

    def import_file(self, filepath):
        """Import image found at filepath."""

        if os.path.split(filepath)[0] == "":
            filepath = os.path.join(self.folder_name, filepath)

        self.current_file = os.path.split(filepath)[1]
        filetype = os.path.splitext(self.current_file)[1]

        if filetype == ".oir":
            image = utils.oir_import(filepath)
        else:
            image = utils.oif_import(filepath, channels=False)

        self.current_image = image

    def import_cellpose_model(self):
        """Import cellpose model."""

        import mxnet
        from cellpose import models

        model = models.Cellpose(device=mxnet.cpu(), model_type=self.cellpose_type)
        self.model = model

    def calculate_median(self, channel):
        """Calculate median filtered image of channel."""

        ch = self.channels.index(channel)
        self.current_image_med = skimage.filters.median(
            self.current_image[:, :, ch], skimage.morphology.disk(2)
        )
        self.current_median_channel = channel

    def segment_cells(self, channel, num_low_pixels=10000, num_std=1):
        """Segment cells found in a given channel. Estimates background
        and sets hard threshold.

        Parameters
        ----------
        channel : str
            channel name
        num_low_pixels : int
            number of the lowest intensity pixels to
            use as background estimation
        num_std : float
            number of std above the mean for threshold

        """

        ch = self.channels.index(channel)
        cell_mask = utils.segment_cells(self.current_image[:, :, ch])

        '''data = np.sort(np.ravel(self.current_image[:, :, ch]))
        data = np.log(data)
        ydata, xdata = np.histogram(data, bins=np.arange(0, data.max(), 0.05))
        xdata = [0.5 * (xdata[x] + xdata[x + 1]) for x in range(len(xdata) - 1)]
        # find first point lower than half max after peak
        first_low = (
            np.argwhere(
                (ydata > 0.5 * ydata.max())[ydata.argmax()::]==False
            )[0][0]
            + ydata.argmax()
        )
        out, _ = utils.fit_gaussian_hist(
            data[data < xdata[first_low]],
            plotting=False,
            maxbin=xdata[first_low] + 0.5,
            binwidth=0.05,
        )
        threshold = np.exp(out[0][1] + num_std * out[0][2])
        cell_mask = skimage.filters.median(
            self.current_image[:, :, ch], selem=skimage.morphology.disk(5)) > threshold
        cell_mask = skimage.morphology.binary_opening(
            cell_mask, selem=skimage.morphology.disk(10))'''

        '''# simplistic threshold
        back_pix = np.sort(np.ravel(self.current_image[:, :, ch]))[0:num_low_pixels]
        back_mean = np.mean(back_pix)
        back_std = np.std(back_pix)

        cell_mask = self.current_image[:, :, ch] > back_mean + num_std * back_std
        cell_mask = skimage.morphology.binary_opening(
            cell_mask, selem=skimage.morphology.disk(10)
        )'''

        self.current_cell_mask = cell_mask
        self.cell_segmentation[self.current_file] = cell_mask

    def segment_nuclei(self, channel):
        """Segment nuclei found in a given channel using a custom method."""
        ch = self.channels.index(channel)

        nucle_seg = utils.segment_nuclei(
            self.current_image[:, :, ch], radius=0)

        self.nuclei_segmentation[self.current_file] = nucle_seg

    def segment_nuclei_cellpose(self, channel):
        """Semgment nuclei found in a given channel using cellpose."""

        ch = self.channels.index(channel)

        if self.model is None:
            print("No cellpose model provided")
        else:
            nucle_seg = utils.segment_nuclei_cellpose(
                self.current_image[:, :, ch], self.model, self.cellpose_diam
            )

            self.nuclei_segmentation[self.current_file] = nucle_seg

    def segment_nucleiML(self, channel):
        """Semgment nuclei found in a given channel using the manually
        trained ML model."""

        ch = self.channels.index(channel)
        image = self.current_image[:, :, ch]
        im_rescaled = skimage.transform.rescale(image, 0.5)
        filtered, filter_names = utils.filter_sets(im_rescaled)

        # classify all pixels and update the segmentation layer
        all_pixels = pd.DataFrame(index=np.arange(len(np.ravel(im_rescaled))))
        for ind, x in enumerate(filter_names):
            all_pixels[x] = np.ravel(filtered[ind])
        predictions = self.ml.predict(all_pixels)

        predicted_image = np.reshape(predictions, im_rescaled.shape)
        if self.minsize > 0:
            predicted_image = utils.remove_small(predicted_image, self.minsize)

        predicted_image_upscaled = skimage.transform.resize(
            predicted_image, image.shape, order=0, preserve_range=True
        )

        labeled_mask = predicted_image_upscaled == 2
        labeled_mask = skimage.morphology.label(labeled_mask)
        self.nuclei_segmentation[self.current_file] = labeled_mask

    def segment_bacteria(self, channel, bact_width=5, bact_len=5, n_std=10):
        """Segment bacteria found in a given channel. Uses a series of rotated
        matching templates and a 3D rotation-volume segmentation."""

        # recover nuclei and cell mask
        if self.masking == 'both':
            nucl_mask = self.nuclei_segmentation[self.current_file] > 0
            cell_mask = self.cell_segmentation[self.current_file]
            final_mask = nucl_mask + cell_mask
        elif self.masking == 'nuclei':
            final_mask = self.nuclei_segmentation[self.current_file] > 0
        elif self.masking == 'cells':
            nucl_mask = self.nuclei_segmentation[self.current_file] > 0
            cell_mask = self.cell_segmentation[self.current_file]
            cell_mask = cell_mask & ~nucl_mask
            final_mask = cell_mask.astype(bool)

        # calculate median filter image
        self.calculate_median(channel)
        image = self.current_image_med

        remove_small, all_match, rotation_vol_label = utils.segment_bacteria(
            image, final_mask, n_std, bact_len, bact_width, self.corr_threshold, self.min_corr_vol)

        self.bacteria_segmentation[self.current_file] = remove_small

        self.all_match = all_match
        self.rotation_vol_label = rotation_vol_label

    def segment_actintails(self, channel, bact_width=9, bact_len=17, n_std=3):
        '''Detect actin tails. Same general approach as for bacteria by
        template matching of rotating tube-like feature'''

        # recover nuclei and cell mask
        nucl_mask = self.nuclei_segmentation[self.current_file] > 0
        cell_mask = self.cell_segmentation[self.current_file]

        # remove bright nuclei regions
        cell_mask = cell_mask & ~nucl_mask
        cell_mask = cell_mask.astype(bool)

        # calculate median filter image
        self.calculate_median(channel)
        image = self.current_image_med

        remove_small = utils.segment_actin(
            image, cell_mask, bact_len, bact_width, n_std, self.min_corr_vol)

        self.actin_segmentation[self.current_file] = remove_small

    def bact_measure(self):
        """Measure bacteria properties in all images."""

        bact_labels = self.bacteria_segmentation[self.current_file]
        if bact_labels.max() > 0:
            dataframes = []
            for x in range(len(self.channels)):
                if self.channels[x] is not None:
                    measurements = skimage.measure.regionprops_table(
                        bact_labels,
                        self.current_image[:, :, x],
                        properties=(
                            "mean_intensity", "label", "area", 
                            "eccentricity"),
                    )
                    dataframes.append(
                        pd.DataFrame(
                            {
                                **measurements,
                                **{"channel": self.channels[x]},
                                **{"filename": self.current_file},
                            }
                        )
                    )

            measure_df = pd.concat(dataframes)
            self.bact_measurements[self.current_file] = measure_df

    def run_analysis(
            self, filepath, nucl_channel=None, bact_channel=None,
            cell_channel=None, actin_channel=None):
        """Run complete segmentation for a specific image.

        Parameters
        ----------
        filepath : str
            path of image to analyze
        nucl_channel : str
            nuclei channel name
        bact_channel : str
            bacteria channel name
        cell_channel : str
            cell channel name
        actin_channel : str
            actin channel name

        """

        self.nucl_channel = nucl_channel
        self.bact_channel = bact_channel
        self.cell_channel = cell_channel
        self.actin_channel = actin_channel

        self.import_file(filepath)

        if self.use_ml:
            if self.ml is None:
                print("No ML training available. Load one.")
                return False
            else:
                self.segment_nucleiML(nucl_channel)
        elif self.use_cellpose:
            self.segment_nuclei_cellpose(nucl_channel)
        else:
            self.segment_nuclei(nucl_channel)

        self.segment_cells(cell_channel)
        self.segment_bacteria(bact_channel)
        
        if actin_channel is not None:
            self.segment_actintails(actin_channel)
        self.bact_measure()

        return True

    def save_segmentation(self):
        """Save segmentation information as pkl file."""

        if self.folder_name is None:
            print("No folder_name specified")
            return None

        if not os.path.isdir(os.path.join(self.folder_name, self.saveto)):
            os.makedirs(
                os.path.join(self.folder_name, self.saveto), exist_ok=True)

        file_to_save = os.path.join(
            self.folder_name, self.saveto,
            os.path.split(self.folder_name)[-1] + ".pkl"
        )

        with open(file_to_save, "wb") as f:
            to_export = {
                "bact_channel": self.bact_channel,
                "nucl_channel": self.nucl_channel,
                "cell_channel": self.cell_channel,
                "actin_channel": self.actin_channel,
                "minsize": self.minsize,
                "fillholes": self.fillholes,
                "nuclei_segmentation": self.nuclei_segmentation,
                "bacteria_segmentation": self.bacteria_segmentation,
                "cell_segmentation": self.cell_segmentation,
                "actin_segmentation": self.actin_segmentation,
                "annotations": self.annotations,
                "bact_measurements": self.bact_measurements,
                "channels": self.channels,
                "all_files": self.all_files,
                "ml": self.ml,
                "result": self.result,
                "cellpose_diam": self.cellpose_diam,
            }
            pickle.dump(to_export, f)

    def load_segmentation(self, b=None):
        """Load segmentation file from pkl file."""

        file_to_load = os.path.join(
            self.folder_name, self.saveto,
            os.path.split(self.folder_name)[-1] + ".pkl"
        )

        if not os.path.isfile(file_to_load):
            print("No analysis found")
        else:
            with open(file_to_load, "rb") as f:
                temp = pickle.load(f)

            for k in temp.keys():
                setattr(self, k, temp[k])

            print("Loading Done")

    def show_segmentation(self, local_file):
        """Napari visualisation of segmentation for specifc image."""

        filepath = os.path.join(self.folder_name, local_file)
        if self.bacteria_segmentation[local_file] is None:
            print("not yet segmented")

        self.import_file(filepath)

        viewer = napari.Viewer(ndisplay=2)
        for ind, c in enumerate(self.channels):
            if c is not None:
                image_name = self.current_file + "_" + c
                viewer.add_image(
                    self.current_image[:, :, ind], name=image_name)
        if self.bacteria_segmentation[local_file] is not None:
            viewer.add_labels(
                self.bacteria_segmentation[local_file], name="bactseg",
            )
            viewer.add_labels(
                self.nuclei_segmentation[local_file], name="nucleiseg",
            )
            viewer.add_labels(
                skimage.morphology.label(self.cell_segmentation[local_file]),
                name="cellseg",
            )
            if self.actin_segmentation[local_file] is not None:
                viewer.add_labels(
                    self.actin_segmentation[local_file], name="actinseg")

        self.viewer = viewer
        self.create_key_bindings()

    def create_key_bindings(self):
        """Add key bindings to go forward and backward accross images"""

        self.viewer.bind_key("w", self.move_forward_callback)
        self.viewer.bind_key("b", self.move_backward_callback)

    def move_forward_callback(self, viewer):
        """move to next image"""

        current_file_index = self.all_files.index(self.current_file)
        current_file_index = (current_file_index + 1) % len(self.all_files)
        self.load_new_view(current_file_index)

    def move_backward_callback(self, viewer):
        """move to previous image"""

        current_file_index = self.all_files.index(self.current_file)
        current_file_index = current_file_index - 1
        if current_file_index < 0:
            current_file_index = len(self.all_files)
        self.load_new_view(current_file_index)

    def load_new_view(self, current_file_index):
        """Replace current data in napari visualisation with data
        of new image. Called when moving forward/backward in files."""

        local_file = self.all_files[current_file_index]

        if self.bacteria_segmentation[local_file] is None:
            print("not yet segmented")

        else:
            self.import_file(os.path.join(self.folder_name, local_file))
            for ind, c in enumerate(self.channels):
                if c is not None:
                    layer_index = [
                        x.name.split(".")[-1].split("_")[1] if "." in x.name else x.name
                        for x in self.viewer.layers
                    ].index(c)
                    self.viewer.layers[layer_index].data = self.current_image[:, :, ind]
                    self.viewer.layers[layer_index].name = self.current_file + "_" + c

            bact_layer_ind = [
                x.name for x in self.viewer.layers].index('bactseg')
            self.viewer.layers[
                bact_layer_ind].data = self.bacteria_segmentation[local_file]

            nucl_layer_ind = [
                x.name for x in self.viewer.layers].index('nucleiseg')
            self.viewer.layers[
                nucl_layer_ind].data = self.nuclei_segmentation[local_file]

            cell_layer_index = [
                x.name for x in self.viewer.layers].index('cellseg')
            self.viewer.layers[
                cell_layer_index].data = skimage.morphology.label(
                self.cell_segmentation[local_file])

            if self.actin_segmentation[local_file] is not None:
                actin_layer_ind = [
                    x.name for x in self.viewer.layers].index('actinseg')
                self.viewer.layers[
                    actin_layer_ind].data = self.actin_segmentation[local_file]
