# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/06_collections.pandas.ipynb (unless otherwise specified).

__all__ = ['folder2df', 'split_dataframe_into_stratified_folds', 'get_dataframe_fold', 'get_dataset_labeling',
           'dataframe_labels_2_int', 'split_dataframe_train_test']

# Cell
import logging
import os
import random
from typing import Union

import pandas as pd
from fastcore.all import L, Path, delegates, ifnone
from sklearn.model_selection import StratifiedKFold, train_test_split
from torchvision.datasets.folder import IMG_EXTENSIONS

# Cell
pd.set_option("display.max_colwidth", None)
_logger = logging.getLogger(__name__)

# Cell
def folder2df(
    directory: Union[str, Path],
    extensions: list = IMG_EXTENSIONS,
    shuffle: bool = False,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Parses all the Images in `directory` and puts them in a `DataFrame` object.

    Arguments:

    - `directory`: path to dirs, for example /home/user/data/**
    - `extensions`: data extension of the Images.
    - `shuffle`: shuffles the resulting `DataFrame` object.
    - `seed`: sets seed for reproducibilty
    """

    random.seed(seed)

    image_list = L()
    target_list = L()

    if not isinstance(directory, Path):
        directory = Path(directory)

    for label in directory.ls():
        label = Path(label)
        if os.path.isdir(label):
            for img in label.ls():
                if str(img).lower().endswith(extensions):
                    image_list.append(img)
                    target_list.append(str(label).split(os.path.sep)[-1])

    # fmt: off
    _logger.info(f"Found {len(image_list)} files belonging to {len(set(target_list))} classes.")


    dataframe: pd.DataFrame = pd.DataFrame()
    dataframe["image_id"] = image_list
    dataframe["target"] = target_list
    if shuffle:
        dataframe = dataframe.sample(frac=1, random_state=seed).reset_index(inplace=False, drop=True)
    # fmt: on
    return dataframe

# Cell
@delegates(StratifiedKFold)
def split_dataframe_into_stratified_folds(
    dataframe: pd.DataFrame,
    label_column: str,
    fold_column: str = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Makes stratified folds in `dataframe`. `label_column` is the column to use for split.
    Split Id is given in `fold_column`. Set `random_state` for reproducibility.
    """
    # preserve the original copy of the dataframe
    data = dataframe.copy()
    skf = StratifiedKFold(**kwargs)
    fold_column = ifnone(fold_column, "kfold")

    ys = data[label_column]
    data[fold_column] = -1

    for i, (train_index, test_index) in enumerate(skf.split(X=data, y=ys)):
        data.loc[test_index, fold_column] = i

    return data

# Cell
def get_dataframe_fold(dataframe: pd.DataFrame, split_column: str, split_idx: int):
    """
    Grab the train and validation splits from the dataframe. Splits
    are inferred from `split_column`. The columns with split_idx are
    the validation columns and rest are train columns.
    """
    data = dataframe.copy()
    train_data = data.loc[data[split_column] != split_idx]
    valid_data = data.loc[data[split_column] == split_idx]
    train_data.reset_index(drop=True, inplace=True)
    valid_data.reset_index(drop=True, inplace=True)
    return train_data, valid_data

# Cell
def get_dataset_labeling(dataframe: pd.DataFrame, label_column: str):
    """
    Prepares a mapping using unique values from `label_columns`.
    Returns: a `dictionary` mapping from tag to labels
    """
    tag_to_labels = {
        str(class_name): label
        for label, class_name in enumerate(sorted(dataframe[label_column].unique()))
    }
    return tag_to_labels

# Cell
def dataframe_labels_2_int(
    dataframe: pd.DataFrame,
    label_column: str,
    return_labelling: bool = False,
):
    """
    Converts the labels of the `dataframe` in `label_column` to integers. Set `return_labelling` to
    return the dictionary for labels.
    """
    data = dataframe.copy()
    tag_to_labels = get_dataset_labeling(data, label_column=label_column)
    data[label_column] = data[label_column].apply(func=lambda x: tag_to_labels[str(x)])
    if return_labelling:
        return data, tag_to_labels
    else:
        return data

# Cell
@delegates(train_test_split)
def split_dataframe_train_test(dataframe: pd.DataFrame, **kwargs):
    """
    Split dataframe in train and test part.
    """
    data = dataframe.copy()
    df_train, df_test = train_test_split(data, **kwargs)
    return df_train, df_test