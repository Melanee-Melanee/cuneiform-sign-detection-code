import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from tqdm import tqdm

from skimage.color import label2rgb

from ..transliteration.TransliterationSet import TransliterationSet
from ..transliteration.SignsStats import SignsStats

from ..evaluations.sign_evaluation_gt import prepare_segment_gt

from ..alignment.line_tl_alignment import compute_line_tl_alignment
from ..alignment.LineFragment import LineFragment, plot_boxes

from ..detection.line_detection import prepare_transliteration, post_process_line_detections, compute_image_label_map


def gen_null_hypo_alignments(didx_list, dataset, bbox_anno, lines_anno, relative_path, saa_version,
                             collection_subfolder, train_data_ext_file, lbl_list, generate_and_save,
                             line_model_version='v007', visualize_hypos=False):

    # setup transliteration set
    tl_set = TransliterationSet(collections=[saa_version], relative_path=relative_path)
    # setup sign statistics
    stats = SignsStats(tblSignHeight=128)

    # for seg_im, seg_idx in dataset:
    for didx in tqdm(didx_list, desc=saa_version):
        seg_im, seg_idx = dataset[didx]
        # access meta
        seg_rec = dataset.assigned_segments_df.loc[seg_idx]
        image_name, scale, seg_bbox, image_path, view_desc = dataset.get_segment_meta(seg_rec)
        res_name = "{}{}".format(image_name, view_desc)

        # load transliteration dataframe
        tl_df, num_lines = tl_set.get_tl_df(seg_rec, verbose=True)

        if len(tl_df) > 0:  # only continue if transliteration is available
            tl_df, num_vis_lines, len_min, len_max = prepare_transliteration(tl_df, num_lines, stats)
            print(float(len_min) / len_max, num_vis_lines)

            # load and prepare annotations of segment
            gt_boxes, gt_labels = prepare_segment_gt(seg_idx, scale, bbox_anno,
                                                     with_star_crop=False)  # depends on sign_detections!
            print('Load annotations: {} gt bboxes found.'.format(len(gt_boxes)))

            sign_detections = None

            # make seg image is large enough for line detector
            if seg_im.size[0] > 224 and seg_im.size[1] > 224 and len(tl_df) > 0:

                # prepare input
                # to numpy
                center_im = np.asarray(seg_im)
                # lbl_ind
                line_res_path = "{}results/results_line/{}/{}".format(relative_path, line_model_version, saa_version)
                lines_file = "{}/{}_lbl_ind.npy".format(line_res_path, res_name)
                # lines_file = "{}/{}_skeleton.npy".format(line_res_path, res_name)
                lbl_ind_x = np.load(lines_file).astype(int)

                # only continue if there is a positive line detection
                # (avoids unnecessary computation and an error in skimage hough_line_peaks)
                if np.any(lbl_ind_x):

                    # for line detection apply postprocessing pipeline
                    (line_hypos, line_segs, segm_labels, ls_labels, dist_interline_median, group2line,
                     h, theta, d, skeleton) = post_process_line_detections(lbl_ind_x, num_vis_lines, len_min, len_max)

                    if len(line_segs) > 0:
                        # compute overlay
                        seg_canvas = compute_image_label_map(segm_labels, center_im.shape)
                        image_label_overlay = label2rgb(seg_canvas, image=center_im)

                    # using line annotations: gt_line_idx for hypo_lines
                    gt_line_assignment = lines_anno.get_assignment_for_line_hypos(seg_idx,
                                                                                  line_hypos.groupby('label').mean())

                    if len(gt_line_assignment) > 0:
                        # clean join on line_hypos
                        line_hypos = line_hypos.join(gt_line_assignment.set_index('hypo_line_lbl'), on='label')
                        ## clean join on line_hypos_agg
                        # line_frag.line_hypos_agg.join(gt_line_assignment.set_index('hypo_line_lbl'))

                    if len(tl_df) > 0:

                        # abort if obvious transliteration / lines mismatch
                        if np.abs(tl_df.line_idx.nunique() - line_hypos.label.nunique()) > 10:
                            print(
                                "CANCEL segment [{}] : Due to obvious transliteration / lines mismatch".format(seg_idx))
                            continue

                        #### line-transliteration alignment problem ####
                        # for train use: align_opt=[False, True, False] (use line annos)
                        line_hypos, path_pts = compute_line_tl_alignment(line_hypos, tl_df, gt_line_assignment,
                                                                         segm_labels, stats, center_im, sign_detections,
                                                                         visualize=False,
                                                                         align_opt=[True, False, False])  # CHANGE HERE

                        # FINISH lines-tl alignment

                        # create line fragment (tl_line should be assigned before?!)
                        line_frag = LineFragment(line_hypos, segm_labels, tl_df, stats, center_im, sign_detections)
                        # get assigned tl indices
                        assigned_tl_indices = line_frag.get_assigned_lines_idx()
                        # get assignment space (cartesian product of tl_line_indices and hypo_line_indices)
                        hypo_line_indices, tl_line_indices = line_frag.get_alignment_space()

                        if visualize_hypos:
                            # generate conditional hypo
                            tab_t_hypos = line_frag.tab_create_null_hypo_alignments()
                            if len(tab_t_hypos) > 0:
                                if False:
                                    # filter using nms
                                    nms_th = 0.6
                                    keep = nms(tab_t_hypos[:, 4:8], tab_t_hypos[:, 3], threshold=nms_th)
                                    tab_t_hypos = tab_t_hypos[keep]
                                # visualize
                                plot_boxes(tab_t_hypos[:, 4:8])
                                plt.imshow(line_frag.input_im, cmap='gray')

                        # save to test
                        if generate_and_save:
                            line_frag.tab_generate_null_hypo_training_data(collection_subfolder,
                                                                           train_data_ext_file,
                                                                           image_name, image_path, scale, seg_idx,
                                                                           seg_bbox,
                                                                           lbl_list, append=True)
                else:
                    print('No lines detected for {}[{}] and thus no alignment performed!'.format(image_name, seg_idx))
            else:
                print('segment image of for {}[{}] too small!'.format(image_name, seg_idx))

            # print plot
            plt.show()

