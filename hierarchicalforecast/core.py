# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/core.ipynb (unless otherwise specified).

__all__ = ['bottom_up', 'top_down', 'crossprod', 'min_trace', 'HierarchicalReconciliation']

# Cell
from dataclasses import dataclass
from functools import partial
from inspect import signature
from typing import Callable, List

import numpy as np
import pandas as pd

# Cell
def _reconcile(S: np.ndarray, P: np.ndarray, W: np.ndarray,
               y_hat: np.ndarray, SP: np.ndarray = None):
    if SP is None:
        SP = S @ P
    return np.matmul(SP, y_hat)

# Cell
def bottom_up(S: np.ndarray,
              y_hat: np.ndarray):
    n_hiers, n_bottom = S.shape
    P = np.eye(n_bottom, n_hiers, k=(n_hiers - n_bottom), dtype=np.float32)
    W = np.eye(n_hiers, dtype=np.float32)
    return _reconcile(S, P, W, y_hat)

# Cell
def top_down(S: np.ndarray,
             y_hat: np.ndarray,
             y: np.ndarray,
             idx_bottom: List[int],
             method: str):
    n_hiers, n_bottom = S.shape
    idx_top = int(S.sum(axis=1).argmax())
    #add strictly hierarchical assert

    if method == 'forecast_proportions':
        raise NotImplementedError(f'Method {method} not implemented yet')
    else:
        y_top = y[idx_top]
        y_btm = y[idx_bottom]
        if method == 'average_proportions':
            prop = np.mean(y_btm / y_top, axis=1)
        elif method == 'proportion_averages':
            prop = np.mean(y_btm, axis=1) / np.mean(y_top)
        else:
            raise Exception(f'Unknown method {method}')
    P = np.zeros_like(S).T
    P[:, idx_top] = prop
    W = np.eye(n_hiers, dtype=np.float32)
    return _reconcile(S, P, W, y_hat)

# Cell
def crossprod(x):
    return x.T @ x

# Cell
def min_trace(S: np.ndarray,
              y_hat: np.ndarray,
              residuals: np.ndarray,
              method: str):
    # shape residuals (obs, n_hiers)
    res_methods = ['wls_var', 'mint_cov', 'mint_shrink']
    if method in res_methods and residuals is None:
        raise ValueError(f"For methods {', '.join(res_methods)} you need to pass residuals")
    n_hiers, n_bottom = S.shape
    if method == 'ols':
        W = np.eye(n_hiers)
    elif method == 'wls_struct':
        W = np.diag(hfcst.S @ np.ones((n_bottom,)))
    elif method in res_methods:
        n, _ = residuals.shape
        masked_res = np.ma.array(residuals, mask=np.isnan(residuals))
        covm = np.ma.cov(masked_res, rowvar=False, allow_masked=True).data
        if method == 'wls_var':
            W = np.diag(np.diag(covm))
        elif method == 'mint_cov':
            W = covm
        elif method == 'mint_shrink':
            tar = np.diag(np.diag(covm))
            corm = cov2corr(covm)
            xs = np.divide(residuals, np.sqrt(np.diag(covm)))
            xs = xs[~np.isnan(xs).any(axis=1), :]
            v = (1 / (n * (n - 1))) * (crossprod(xs ** 2) - (1 / n) * (crossprod(xs) ** 2))
            np.fill_diagonal(v, 0)
            corapn = cov2corr(tar)
            d = (corm - corapn) ** 2
            lmd = v.sum() / d.sum()
            lmd = max(min(lmd, 1), 0)
            W = lmd * tar + (1 - lmd) * covm
    else:
        raise ValueError(f'Unkown reconciliation method {method}')

    eigenvalues, _ = np.linalg.eig(W)
    if any(eigenvalues < 1e-8):
        raise Exception('min_trace needs covariance matrix to be positive definite.')

    R = S.T @ np.linalg.inv(W)
    P = np.linalg.inv(R @ S) @ R

    return _reconcile(S, P, W, y_hat)

# Internal Cell
def _build_fn_name(fn, *args, inner_args) -> str:
    fn_name = fn.__name__
    func_params = signature(fn).parameters
    func_args = list(func_params.items())
    func_args = [(name, arg) for (name, arg) in func_args if arg.name not in inner_args]
    changed_kwargs = {
        name: value
        for value, (name, arg) in zip(args, func_args)
        if arg.default != value
    }
    if changed_kwargs:
        changed_params = [f'{name}-{value}' for name, value in changed_kwargs.items()]
        fn_name += '_' + '_'.join(changed_params)
    return fn_name, changed_kwargs

# Internal Cell
def _as_tuple(x):
    if isinstance(x, tuple):
        return x
    return (x,)

# Cell
class HierarchicalReconciliation:

    def __init__(self, reconcile_fns: List[Callable]):
        self.reconcile_fns = reconcile_fns

    def reconcile(self, Y_h: pd.DataFrame, Y_df: pd.DataFrame, S: pd.DataFrame):
        """Reconcile base forecasts.

            Parameters
            ----------
            Y_h: pd.DataFrame
                Base forecasts with columns ['ds']
                and models to reconcile indexed by 'unique_id'.
            Y_df: pd.DataFrame
                Training set of base time series with columns
                ['ds', 'y'] indexed by 'unique_id'
                If a function of `self.reconcile_fns` receives
                residuals, `Y_df` must include them as columns.
            S: pd.DataFrame
                Summing matrix of size (hierarchies, bottom).
        """
        drop_cols = ['ds', 'y'] if 'y' in Y_h.columns else ['ds']
        model_names = Y_h.drop(columns=drop_cols, axis=1).columns.to_list()
        common_vals = dict(
            y = Y_df.pivot(columns='ds', values='y').loc[S.index].values,
            S = S.values,
            idx_bottom = [S.index.get_loc(col) for col in S.columns]
        )
        fcsts = Y_h.copy()
        for reconcile_fn_args in self.reconcile_fns:
            reconcile_fn, *args = _as_tuple(reconcile_fn_args)
            reconcile_fn_name, fn_kwargs = _build_fn_name(
                reconcile_fn, *args,
                inner_args=['y', 'S', 'idx_bottom', 'y_hat', 'residuals']
            )
            has_res = 'residuals' in signature(reconcile_fn).parameters
            for model_name in model_names:
                y_hat_model = Y_h.pivot(columns='ds', values=model_name).loc[S.index].values
                if has_res:
                    common_vals['residuals'] = Y_df.pivot(columns='ds', values=model_name).loc[S.index].values.T
                kwargs = [key for key in signature(reconcile_fn).parameters if key in common_vals.keys()]
                kwargs = {key: common_vals[key] for key in kwargs}
                p_reconcile_fn = partial(reconcile_fn, y_hat=y_hat_model, **kwargs)
                fcsts_model = p_reconcile_fn(**fn_kwargs)
                fcsts[f'{model_name}/{reconcile_fn_name}'] = fcsts_model.flatten()
                if has_res:
                    del common_vals['residuals']
        return fcsts