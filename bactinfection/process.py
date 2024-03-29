from . import dataloader
from . segmentation import segment_bacteria, segment_nucl_cellpose, segment_cell_cellpose
import skimage.io
import numpy as np
from pathlib import Path
import os


def single_image_analysis(
    filepath,
    analysis_folder,
    diameter_nucl,
    nucl_channel,
    cell_channel,
    bact_channel,
    bact_width,
    bact_len,
    corr_threshold,
    min_corr_vol,
    n_std=0,
    nucl_model_type="nuclei",
    resample=False,
    masking="cell_no_nuclei",
    cell_precalc=False,
    diameter_cell=200,
    background_estim='smo'
):

    analysis_folder = Path(analysis_folder)
    if not analysis_folder.exists():
        os.makedirs(analysis_folder)

    filepath = Path(filepath)
    report_file = filepath.joinpath(str(filepath).replace(".oir", "_error.txt"))
    #report_file = Path(str(filepath).replace('.ipynb', '.test'))

    try:
        stack, channels = dataloader.oirloader(filepath)
    except:
        with open(report_file, "a+") as f:
            f.write("Loading error")
        return None

    for c in [nucl_channel, bact_channel]:
        if c not in channels:
            with open(report_file, "a+") as f:
                f.write(nucl_channel + "channel not existing")
            return None

    model = None

    #try:
    # detect nuclei
    im_nucl = stack[:, :, channels.index(nucl_channel)]
    nucl_mask = segment_nucl_cellpose(
        model, im_nucl, diameter_nucl,
        model_type=nucl_model_type, resample=resample
    )
    save_to = analysis_folder.joinpath(Path(filepath).stem + "_nucl_seg.tif")
    skimage.io.imsave(save_to, nucl_mask, check_contrast=False)
    if np.max(nucl_mask) == 0:
        with open(report_file, "a+") as f:
            f.write("No nuclei found")
        return None

    if cell_channel is not None:
        save_to = analysis_folder.joinpath(Path(filepath).stem + "_cell_seg.tif")
        if cell_precalc:
            cell_mask = skimage.io.imread(save_to)
        else:
            im_cell = stack[:, :, channels.index(cell_channel)]
            cell_mask = segment_cell_cellpose(model, im_cell, diameter_cell)
            skimage.io.imsave(save_to, cell_mask.astype(np.uint8), check_contrast=False)

        if np.max(cell_mask) == 0:
            with open(report_file, "a+") as f:
                f.write("No cell found")
            return None

    # detect bacteria
    im_bact = stack[:, :, channels.index(bact_channel)]

    #im_bact = skimage.filters.median(im_bact, skimage.morphology.disk(2))
    nucl_mask2 = nucl_mask > 0

    # choose in which regions bacteria should be counted: cell and not nuclei,
    # only cells or only nuclei
    if masking == "Cells no nuclei":
        final_mask = np.logical_and(cell_mask>0, np.logical_not(nucl_mask2))
    elif masking == "Cells":
        final_mask = cell_mask>0
    elif masking == "Nuclei":
        final_mask = nucl_mask2
    elif masking == "none":
        final_mask = None
    else:
        with open(report_file, "a+") as f:
            f.write("No appropriate masking found")
        return None

    final_mask = final_mask.astype(bool)
    bact_mask, _, _ = segment_bacteria(
        image=im_bact,
        background_estim=background_estim,
        final_mask=final_mask,
        n_std=n_std,
        bact_len=bact_len,
        bact_width=bact_width,
        corr_threshold=corr_threshold,
        min_corr_vol=min_corr_vol,
    )
    bact_mask = skimage.morphology.label(bact_mask)
    save_to = analysis_folder.joinpath(Path(filepath).stem + "_bact_seg.tif")
    skimage.io.imsave(save_to, bact_mask.astype(np.uint16), check_contrast=False)

    #except:
    #    with open(report_file, "a+") as f:
    #        f.write("Unknown error happened during segmentation")
    #        return None

def multiple_images_dask(
    client,
    file_list,
    analysis_folder,
    diameter_nucl,
    nucl_channel,
    cell_channel,
    bact_channel,
    bact_width,
    bact_len,
    corr_threshold,
    min_corr_vol,
    n_std=0,
    nucl_model_type="nuclei",
    resample=False,
    masking="cell_no_nuclei",
    cell_precalc=False,
    diameter_cell=200,
    background_estim='smo'):

    # Segment all images but don't do tracking (selection of label)
    segmented = [
        client.submit(
            single_image_analysis,
            filepath=file_list[k],
            analysis_folder=analysis_folder,
            diameter_nucl=diameter_nucl,
            nucl_channel=nucl_channel,
            bact_channel=bact_channel,
            cell_channel=cell_channel,
            bact_len=bact_len,
            bact_width=bact_width,
            corr_threshold=corr_threshold,
            min_corr_vol=min_corr_vol,
            n_std=n_std,
            nucl_model_type=nucl_model_type,
            resample=resample,
            masking=masking,
            background_estim=background_estim,
            )
        for k in range(len(file_list))
    ]
    for k in range(len(file_list)):
        future = segmented[k]
        segmented[k] = future.result()
        future.cancel()
        del future