# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/01a_core.nn.losses.ipynb (unless otherwise specified).

__all__ = ['LOSS_REGISTRY', 'SoftTargetCrossEntropy', 'LOSS_REGISTRY', 'LabelSmoothingCrossEntropy',
           'BinarySigmoidFocalLoss', 'FocalLoss', 'build_loss']

# Cell
import logging
from typing import *

import torch
import torch.nn.functional as F
import torch.nn.modules.loss as torch_losses
from fastcore.all import store_attr
from fvcore.nn import sigmoid_focal_loss
from omegaconf import DictConfig, OmegaConf
from timm.loss import SoftTargetCrossEntropy
from torch import Tensor, nn

from .utils import maybe_convert_to_onehot
from ..utils.structures import Registry

_logger = logging.getLogger(__name__)

# Cell
LOSS_REGISTRY = Registry("Loss Registry")
LOSS_REGISTRY.__doc__ = """
Registry of Loss Functions
"""

# Cell
#nbdev_comment _all_ = ["SoftTargetCrossEntropy", "LOSS_REGISTRY"]

# Cell
@LOSS_REGISTRY.register()
class LabelSmoothingCrossEntropy(nn.Module):
    "Cross Entropy Loss with Label Smoothing"

    def __init__(
        self,
        eps: float = 0.1,
        reduction: str = "mean",
        weight: Optional[Tensor] = None,
    ):
        super(LabelSmoothingCrossEntropy, self).__init__()
        store_attr("eps, reduction, weight")

    def forward(self, input: Tensor, target: Tensor):
        """
        Shape:
        - Input  : $(N,C)$ where $N$ is the mini-batch size and $C$ is the total number of classes
        - Target : $(N)$ where each value is $0 \leq {targets}[i] \leq C-10≤targets[i]≤C−1$
        - Output: scalar. If `reduction` is `none`, then $(N, *)$ , same shape as input.
        """
        c = input.size()[1]
        log_preds = F.log_softmax(input, dim=1)
        if self.reduction == "sum":
            loss = -log_preds.sum()
        else:
            loss = -log_preds.sum(dim=1)
            if self.reduction == "mean":
                loss = loss.mean()
        # fmt: off
        loss = loss * self.eps / c + (1 - self.eps) * F.nll_loss(log_preds, target.long(), weight=self.weight, reduction=self.reduction)
        # fmt: on
        return loss

# Cell
@LOSS_REGISTRY.register()
class BinarySigmoidFocalLoss(nn.Module):
    """
    Creates a criterion that computes the focal loss between binary `input` and `target`.
    Focal Loss used in RetinaNet for dense detection: https://arxiv.org/abs/1708.02002.

    Source: https://github.com/facebookresearch/fvcore/blob/master/fvcore/nn/focal_loss.py
    """

    def __init__(
        self,
        alpha: float = -1,
        gamma: float = 2,
        reduction: str = "mean",
    ):
        super(BinarySigmoidFocalLoss, self).__init__()
        store_attr("alpha, gamma, reduction")

    def forward(self, input: Tensor, target: Tensor):
        """
        Shape:
        - Input: : $(N, *)$ where $*$ means, any number of additional dimensions.
        - Target: : $(N, *)$, same shape as the input.
        - Output: scalar. If `reduction` is 'none', then $(N, *)$ , same shape as input.
        """
        loss = sigmoid_focal_loss(input, target, self.gamma, self.alpha, self.reduction)
        return loss

# Cell
@LOSS_REGISTRY.register()
class FocalLoss(nn.Module):
    """
    Same as `nn.CrossEntropyLoss` but with focal paramter, `gamma`.
    Focal Loss used in RetinaNet for dense detection: https://arxiv.org/abs/1708.02002.
    Focal loss is computed as follows :
    ${FL}(p_t)$ = $\alpha(1 - p_t)^{\gamma}{log}(p_t)$

    Source: https://kornia.readthedocs.io/en/latest/_modules/kornia/losses/focal.html
    """

    def __init__(
        self,
        alpha: float = 1,
        gamma: float = 2,
        reduction: str = "mean",
        eps: float = 1e-8,
    ):

        super(FocalLoss, self).__init__()
        store_attr("alpha, gamma, reduction, eps")

    def forward(self, input: Tensor, target: Tensor):
        """
        Shape:
        - Input  : $(N,C)$ where $N$ is the mini-batch size and $C$ is the total number of classes
        - Target : $(N)$ where each value is $0 \leq {targets}[i] \leq C-10≤targets[i]≤C−1$
        """
        if not len(input.shape) >= 2:
            raise ValueError(
                "Invalid input shape, we expect BxCx*. Got: {}".format(input.shape)
            )

        if input.size(0) != target.size(0):
            raise ValueError(
                "Expected input batch_size ({}) to match target batch_size ({}).".format(
                    input.size(0), target.size(0)
                )
            )

        n = input.size(0)

        # compute softmax over the classes axis
        softmax_inputs: Tensor = F.softmax(input, dim=1) + self.eps

        # create the labels one hot tensor
        one_hot_targs: Tensor = maybe_convert_to_onehot(target, softmax_inputs)

        # compute the actual focal loss
        focal_weight = torch.pow(-softmax_inputs + 1.0, self.gamma)

        focal_factor = -self.alpha * focal_weight * torch.log(softmax_inputs)

        loss = torch.sum(one_hot_targs * focal_factor, dim=1)

        if self.reduction == "none":
            loss = loss
        elif self.reduction == "mean":
            loss = torch.mean(loss)
        elif self.reduction == "sum":
            loss = torch.sum(loss)
        else:
            raise NotImplementedError(
                "Invalid reduction mode: {}".format(self.reduction)
            )
        return loss

# Cell
def build_loss(config: DictConfig):
    """
    Builds a ClassyLoss from a config.
    This assumes a 'name' key in the config which is used to determine what
    model class to instantiate. For instance, a config `{"name": "my_loss",
    "foo": "bar"}` will find a class that was registered as "my_loss". A custom
    loss must first be registerd into `LOSS_REGISTRY`.
    """

    assert "name" in config, f"name not provided for loss: {config}"
    config = OmegaConf.to_container(config, resolve=True)

    name = config["name"]
    args = config["init_args"]

    # if we are passing weights, we need to change the weights from a list to a tensor
    if args is not None:
        if "weight" in args and args["weight"] is not None:
            args["weight"] = torch.tensor(args["weight"], dtype=torch.float)

    if name in LOSS_REGISTRY:
        instance = LOSS_REGISTRY.get(name)

    # the name should be available in torch.nn.modules.loss
    else:
        assert hasattr(torch_losses, name), (
            f"{name} isn't a registered loss"
            ", nor is it available in torch.nn.modules.loss"
        )
        instance = getattr(torch_losses, name)

    if args is not None:
        loss = instance(**args)
    else:
        loss = instance()
    _logger.info("Built loss function: {}".format(loss.__class__.__name__))
    return loss