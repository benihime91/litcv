# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/03_core-classes.ipynb (unless otherwise specified).

__all__ = ['Configurable', 'BasicModule', 'get_callable_name', 'get_callable_dict', 'setup_metrics', 'DefaultTask']

# Cell
import copy
import logging
import math
from abc import ABC, ABCMeta, abstractmethod
from contextlib import contextmanager
from typing import *

import hydra
import pytorch_lightning as pl
import torch
import torchmetrics
from fastcore.all import L, ifnone, noop
from omegaconf import DictConfig, OmegaConf
from torch.nn import Module

from .optimizer import OPTIM_REGISTRY
from .schedules import SCHEDULER_REGISTRY
from .torch_utils import trainable_params
from .utils.logger import log_main_process

_logger = logging.getLogger(__name__)

# Cell
class Configurable(ABC):
    """
    Helper Class to instantiate obj from config
    """

    @classmethod
    def from_config_dict(cls, config: DictConfig, **kwargs):
        """
        Instantiates object using `DictConfig-based` configuration. You can optionally
        pass in extra `kwargs`
        """
        # Resolve the config dict
        if isinstance(config, DictConfig):
            config = OmegaConf.to_container(config, resolve=True)
            config = OmegaConf.create(config)

        if "_target_" in config:
            # regular hydra-based instantiation
            instance = hydra.utils.instantiate(config=config, **kwargs)
        else:
            # instantiate directly using kwargs
            try:
                instance = cls(cfg=config, **kwargs)
            except:
                cfg = OmegaConf.to_container(config, resolve=True)
                instance = cls(**config, **kwargs)

        if not hasattr(instance, "_cfg"):
            instance._cfg = config
        return instance

    def to_config_dict(self) -> DictConfig:
        """Returns object's configuration to config dictionary"""
        if (
            hasattr(self, "_cfg")
            and self._cfg is not None
            and isinstance(self._cfg, DictConfig)
        ):
            # Resolve the config dict
            config = OmegaConf.to_container(self._cfg, resolve=True)
            config = OmegaConf.create(config)
            OmegaConf.set_struct(config, True)
            self._cfg = config

            return self._cfg
        else:
            raise NotImplementedError(
                "to_config_dict() can currently only return object._cfg but current object does not have it."
            )

# Cell
class BasicModule(Module, Configurable, metaclass=ABCMeta):
    """
    Abstract class offering interface which should be implemented by all `Backbones`,
    `Heads` and `Meta Archs` in gale.
    """

    @abstractmethod
    def forward(self) -> Any:
        """
        The main logic for the model lives here. Can return either features, logits
        or loss.
        """
        raise NotImplementedError

    @abstractmethod
    def build_param_dicts(self) -> Union[Iterable, List[Dict], Dict, List]:
        """
        Should return the iterable of parameters to optimize or dicts defining parameter groups
        for the Module.
        """
        raise NotImplementedError

    @property
    def param_lists(self):
        "Returns the list of paramters in the module"
        return [p for p in self.parameters()]

    def all_params(self, n=slice(None), with_grad=False):
        "List of `param_groups` upto n"
        res = L(p for p in self.param_lists[n])
        return (
            L(o for o in res if hasattr(o, "grad") and o.grad is not None)
            if with_grad
            else res
        )

    def _set_require_grad(self, rg, p):
        p.requires_grad_(rg)

    def unfreeze(self) -> None:
        """Unfreeze all parameters for training."""
        for param in self.parameters():
            param.requires_grad = True

        self.train()

    def freeze(self) -> None:
        """Freeze all params for inference & set model to eval"""
        for param in self.parameters():
            param.requires_grad = False
        self.eval()

    def freeze_to(self, n: int) -> None:
        "Freeze parameter groups up to `n`"
        self.frozen_idx = n if n >= 0 else len(self.param_lists) + n
        if self.frozen_idx >= len(self.param_lists):
            _logger.warning(
                f"Freezing {self.frozen_idx} groups; model has {len(self.param_lists)}; whole model is frozen."
            )

        for o in self.all_params(slice(n, None)):
            self._set_require_grad(True, o)

        for o in self.all_params(slice(None, n)):
            self._set_require_grad(False, o)

    @contextmanager
    def as_frozen(self):
        """
        Context manager which temporarily freezes a module, yields control
        and finally unfreezes the module.
        """
        self.freeze()

        try:
            yield
        finally:
            self.unfreeze()

# Cell
def get_callable_name(fn_or_class: Union[Callable, object]) -> str:
    return getattr(fn_or_class, "__name__", fn_or_class.__class__.__name__).lower()


def get_callable_dict(fn: Union[Callable, Mapping, Sequence]) -> Union[Dict, Mapping]:
    if isinstance(fn, Mapping):
        return fn
    elif isinstance(fn, Sequence):
        return {get_callable_name(f): f for f in fn}
    elif callable(fn):
        return {get_callable_name(fn): fn}


def setup_metrics(
    metrics: Union[torchmetrics.Metric, Mapping, Sequence, None]
) -> torch.nn.ModuleDict:
    m = {} if metrics is None else get_callable_dict(metrics)
    return torch.nn.ModuleDict(m)

# Cell
class DefaultTask(pl.LightningModule):
    """
    Interface for Pytorch-lightning based Gale modules
    """

    is_restored = True

    def __init__(
        self,
        cfg: DictConfig,
        trainer: Optional[pl.Trainer] = None,
        metrics: Union[torchmetrics.Metric, Mapping, Sequence, None] = None,
    ):
        """
        Base class from which all PyTorch Lightning Tasks in Gale should inherit.
        Provides a few helper functions primarily for optimization.

        Arguments:
        1. `cfg` `(DictConfig)`:  configuration object. cfg object should be inherited from `BaseGaleConfig`.
        2. `trainer` `(Optional, pl.Trainer)`: Pytorch Lightning Trainer instance
        3. `metrics` `(Optional)`: Metrics to compute for training and evaluation.
        """
        super().__init__()
        self._cfg = OmegaConf.create(cfg)
        self._cfg = OmegaConf.structured(cfg)

        if trainer is not None and not isinstance(trainer, pl.Trainer):
            raise ValueError(
                f"Trainer constructor argument must be either None or pl.Trainer.But got {type(trainer)} instead."
            )

        self._train_dl = noop
        self._validation_dl = noop
        self._test_dl = noop

        self._optimizer = noop
        self._scheduler = noop

        self._trainer = ifnone(trainer, noop)
        self._metrics = setup_metrics(metrics)
        self._model = noop

        self.save_hyperparameters(self._cfg)

        # if trained is not passed them the Model is being restored
        if self._trainer is not None:
            self.is_restored = False
        else:
            self.is_restored = True

    @abstractmethod
    def forward(self, x: torch.Tensor) -> Any:
        """
        The Forward method for LightningModule, users should modify this method.
        """
        raise NotImplementedError

    def shared_step(self, batch: Any, batch_idx: int, stage: str) -> Dict:
        """
        The common training/validation/test step. Override for custom behavior. This step
        is shared between training/validation/test step. For training/validation/test steps
        `stage` is train/val/test respectively. You training logic should go here avoid directly overriding
        training/validation/test step methods. This step needs to return a dictionary contatining
        the loss to optimize and values to log.
        """
        raise NotImplementedError

    def training_step(self, batch: Any, batch_idx: int) -> Any:
        """
        The training step of the LightningModule. For common use cases you need
        not need to override this method. See `GaleTask.shared_step()`
        """
        output = self.shared_step(batch, batch_idx, stage="train")
        self.log_dict({f"train/{k}": v for k, v in output["logs"].items()})
        return output["loss"]

    def validation_step(self, batch: Any, batch_idx: int) -> None:
        """
        The validation step of the LightningModule. For common use cases you need
        not need to override this method. See `GaleTask.shared_step()`
        """
        output = self.shared_step(batch, batch_idx, stage="validation")
        self.log_dict({f"val/{k}": v for k, v in output["logs"].items()})

    def test_step(self, batch: Any, batch_idx: int) -> None:
        """
        The test step of the LightningModule. For common use cases you need
        not need to override this method. See `GaleTask.shared_step()`
        """
        output = self.shared_step(batch, batch_idx, stage="test")
        self.log_dict({f"test/{k}": v for k, v in output["logs"].items()})

    def configure_optimizers(self) -> Any:
        """
        Choose what optimizers and learning-rate schedulers to use in your optimization.
        See https://pytorch-lightning.readthedocs.io/en/latest/common/optimizers.html
        """
        # if self.setup_optimization() has been called manually no
        # need to call again
        if self._optimizer is noop and self._scheduler is noop:
            self.setup_optimization()

        if self._scheduler is None:
            return self._optimizer
        else:
            return [self._optimizer], [self._scheduler]

    def train_dataloader(self) -> torch.utils.data.DataLoader:
        "Returns the Dataloader used for Training"
        if self._train_dl is not None and self._train_dl is not noop:
            return self._train_dl

    def val_dataloader(self) -> Any:
        "Returns the List of Dataloaders or Dataloader used for Validation"
        if self._validation_dl is not None and self._validation_dl is not noop:
            return self._validation_dl

    def test_dataloader(self) -> Any:
        "Returns the List of Dataloaders or Dataloader used for Testing"
        if self._test_dl is not None and self._test_dl is not noop:
            return self._test_dl

    def process_optim_config(self, opt_conf: DictConfig) -> DictConfig:
        """
        Prepares an optimizer from a string name and its optional config parameters.
        Preprocess the optimization config and adds some infered values like max_steps, max_epochs, etc.
        This method also fills in the values for `max_iters` & `epochs`, `steps_per_epoch` if
        the values are `-1`
        """
        # some optimizers/schedulers need parameters only known dynamically
        # allow users to override the getter to instantiate them lazily

        opt_conf = copy.deepcopy(opt_conf)

        # Force into DictConfig structure
        opt_conf = OmegaConf.create(opt_conf)

        if self._trainer.max_epochs is None and self._trainer.max_steps is None:
            raise ValueError(
                "Either one of max_epochs or max_epochs must be provided in Trainer"
            )
        else:
            max_steps, steps = self.num_training_steps()
            max_epochs = ifnone(self._trainer.max_epochs, max_steps // steps)

        vals = dict(steps_per_epoch=steps, max_steps=max_steps, max_epochs=max_epochs)

        # Force into native dictionary
        opt_conf = OmegaConf.to_container(opt_conf, resolve=True)

        for key, value in vals.items():
            if opt_conf[key] < 1:
                opt_conf[key] = value

        # populate values in learning rate schedulers initialization arguments
        opt_conf = OmegaConf.create(opt_conf)
        sched_config = OmegaConf.to_container(
            opt_conf.scheduler.init_args, resolve=True
        )

        # Force into DictConfig structure
        opt_conf = OmegaConf.create(opt_conf)

        # @TODO: Find a better way to do this
        if "max_iters" in sched_config:
            if sched_config["max_iters"] == -1:
                OmegaConf.update(opt_conf, "scheduler.init_args.max_iters", max_steps)
                log_main_process(
                    _logger,
                    logging.DEBUG,
                    f"Set the value of 'max_iters' to be {max_steps}.",
                )

        if "epochs" in sched_config:
            if sched_config["epochs"] == -1:
                OmegaConf.update(opt_conf, "scheduler.init_args.epochs", max_epochs)
                log_main_process(
                    _logger,
                    logging.DEBUG,
                    f"Set the value of 'epochs' to be {max_epochs}.",
                )

        if "steps_per_epoch" in sched_config:
            if sched_config["steps_per_epoch"] == -1:
                OmegaConf.update(opt_conf, "scheduler.init_args.steps_per_epoch", steps)
                log_main_process(
                    _logger,
                    logging.DEBUG,
                    f"Set the value of 'steps_per_epoch' to be {steps}.",
                )

        if "max_steps" in sched_config:
            if sched_config["max_steps"] == -1:
                OmegaConf.update(opt_conf, "scheduler.init_args.max_steps", max_steps)
                log_main_process(
                    _logger,
                    logging.DEBUG,
                    f"Set the value of 'max_steps' to be {max_steps}.",
                )

        return opt_conf

    def setup_optimization(self, conf: DictConfig = None):
        """
        Prepares an optimizer from a string name and its optional config parameters.
        You can also manually call this method with a valid optimization config
        to setup the optimizers and lr_schedulers.
        """
        if conf is None:
            # See if internal config has `optimization` namespace
            if self._cfg is not None and hasattr(self._cfg, "optimization"):
                conf = self._cfg.optimization

        opt_conf = conf

        # If config is still None, or internal config has no Optim, return without instantiation
        if opt_conf is None:
            log_main_process(
                _logger,
                logging.WARNING,
                "No optimization config found, therefore no optimizer was created",
            )
            self._optimizer, self._scheduler = None, None

        else:
            opt_conf = self.process_optim_config(opt_conf)
            self._optimizer = self.build_optimizer(opt_conf, params=self.param_dicts)
            self._scheduler = self.build_lr_scheduler(
                opt_conf, optimizer=self._optimizer
            )

    def build_optimizer(self, opt_conf: DictConfig, params: Any) -> Any:
        """
        Builds a single optimizer from `opt_conf`. `params` are the parameter
        dict with the weights for the optimizer to optimizer.
        """
        if opt_conf.optimizer.name is None:
            log_main_process(
                _logger,
                logging.WARNING,
                "Optimizer is None, therefore no optimizer will be created.",
            )
            return None
        else:
            opt = opt_conf.optimizer
            opt = OPTIM_REGISTRY.get(opt.name)(params=params, **opt.init_args)
            log_main_process(
                _logger,
                logging.DEBUG,
                "Created optimizer: {}".format(opt.__class__.__name__),
            )
            return opt

    def build_lr_scheduler(
        self, opt_conf: DictConfig, optimizer: torch.optim.Optimizer
    ) -> Any:
        """
        Build the Learning Rate scheduler for current task and optimizer.
        """
        # model must have a max_lrs property
        # so that this value can be inferred to torch One Cycle Schedulers
        max_lrs = self._model.hypers.lr

        if opt_conf.scheduler.name is None:
            log_main_process(
                _logger,
                logging.INFO,
                "scheduler is None, so no scheduler will be created.",
            )
            return None

        else:
            args = opt_conf.scheduler.init_args
            d_args = OmegaConf.to_container(args, resolve=True)
            kwds = {}

            # if a key value is ListConfig then we convert it to simple list
            # also dynamically compute the value of max_lrs
            for key, value in d_args.items():
                if isinstance(value, list):
                    kwds[key] = list(value)
                elif key == "max_lr":
                    kwds["max_lr"] = max_lrs
                else:
                    kwds[key] = value
            instance = SCHEDULER_REGISTRY.get(opt_conf.scheduler.name)
            sch = instance(optimizer=optimizer, **kwds)

            # convert the lr_scheduler to pytorch-lightning LRScheduler dictionary format
            log_main_process(
                _logger,
                logging.DEBUG,
                "Created lr_scheduler : {}.".format(sch.__class__.__name__),
            )

            sch = {
                "scheduler": sch,
                "interval": opt_conf.scheduler.interval,
                "monitor": opt_conf.scheduler.monitor,
            }
            return sch

    def setup_training_data(self, *args, **kwargs) -> None:
        """
        Setups data loader to be used in training
        """
        pass

    def setup_validation_data(self, *args, **kwargs) -> None:
        """
        Setups data loader (s) to be used in validation
        """
        pass

    def setup_test_data(self, *args, **kwargs) -> None:
        """
        (Optionally) Setups data loader to be used in test
        """
        pass

    @property
    def _is_model_being_restored(self):
        """
        Wether the model is being used for inference of training.
        For training it is mandatory to pass in the Training while initializing
        the class
        """
        return self.is_restored

    @_is_model_being_restored.setter
    def _is_model_being_restored(self, x: bool):
        self.is_restored = x

    @property
    def metrics(self):
        """
        Property that returns the metrics for the current Lightning Task
        """
        return self._metrics

    @metrics.setter
    def metrics(
        self, metrics: Union[torchmetrics.Metric, Mapping, Sequence, None] = None
    ):
        self._metrics = setup_metrics(metrics)

    def num_training_steps(self) -> int:
        """
        Total training steps inferred from train dataloader and devices.
        """
        if (
            isinstance(self._trainer.limit_train_batches, int)
            and self._trainer.limit_train_batches != 0
        ):
            dataset_size = self._trainer.limit_train_batches
        elif isinstance(self._trainer.limit_train_batches, float):
            dataset_size = len(self._train_dl)
            dataset_size = int(dataset_size * self._trainer.limit_train_batches)
        else:
            dataset_size = len(self._train_dl)

        num_devices = max(1, self._trainer.num_gpus, self._trainer.num_processes)

        if self._trainer.tpu_cores:
            num_devices = max(num_devices, self._trainer.tpu_cores)

        effective_batch_size = self._trainer.accumulate_grad_batches * num_devices
        max_estimated_steps = (
            dataset_size // effective_batch_size
        ) * self._trainer.max_epochs

        if self._trainer.max_steps and self._trainer.max_steps < max_estimated_steps:
            return self._trainer.max_steps
        return max_estimated_steps, dataset_size

    @property
    def param_dicts(self) -> Union[Iterator, List[Dict]]:
        """
        Property that returns the param dicts for optimization.
        Override for custom training behaviour. Currently returns all the trainable paramters.
        """
        return trainable_params(self)