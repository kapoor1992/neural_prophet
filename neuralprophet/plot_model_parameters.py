import datetime
import logging
from collections import OrderedDict

# from tkinter.messagebox import NO
import numpy as np
import pandas as pd
import torch

from neuralprophet import time_dataset
from neuralprophet.utils import set_y_as_percent

log = logging.getLogger("NP.plotting")

try:
    from matplotlib import pyplot as plt
    from matplotlib.dates import AutoDateFormatter, AutoDateLocator, MonthLocator, num2date
    from matplotlib.ticker import FuncFormatter
    from pandas.plotting import deregister_matplotlib_converters

    deregister_matplotlib_converters()
except ImportError:
    log.error("Importing matplotlib failed. Plotting will not work.")


def plot_parameters(m, quantile, forecast_in_focus=None, weekly_start=0, yearly_start=0, figsize=None, df_name=None):
    """Plot the parameters that the model is composed of, visually.

    Parameters
    ----------
        m : NeuralProphet
            Fitted model
        quantile : float
            The quantile for which the model parameters are to be plotted
        forecast_in_focus : int
            n-th step ahead forecast AR-coefficients to plot
        weekly_start : int
            Specifying the start day of the weekly seasonality plot

            Options
                * (default) ``weekly_start = 0``: starts the week on Sunday
                * ``weekly_start = 1``: shifts by 1 day to Monday, and so on
        yearly_start : int
            Specifying the start day of the yearly seasonality plot.

            Options
                * (default) ``yearly_start = 0``: starts the year on Jan 1
                * ``yearly_start = 1``: shifts by 1 day to Jan 2, and so on
        figsize : tuple
            Width, height in inches.

            Note
            ----
            Default value is set to ``None`` ->  automatic ``figsize = (10, 3 * npanel)``
        df_name : str
            Name of dataframe to refer to data params from original keys of train dataframes

            Note
            ----
            Only used for local normalization in global modeling

    Returns
    -------
        matplotlib.pyplot.figure
            Figure showing the NeuralProphet parameters

    Examples
    --------
    Base usage of :meth:`plot_parameters`

    >>> from neuralprophet import NeuralProphet
    >>> m = NeuralProphet()
    >>> metrics = m.fit(df, freq="D")
    >>> future = m.make_future_dataframe(df=df, periods=365)
    >>> forecast = m.predict(df=future)
    >>> fig_param = m.plot_parameters()

    """
    # Set to True in case of local normalization and unknown_data_params is not True
    overwriting_unknown_data_normalization = False
    if m.config_normalization.global_normalization:
        if df_name is None:
            df_name = "__df__"
        else:
            log.debug("Global normalization set - ignoring given df_name for normalization")
    else:
        if df_name is None:
            log.warning("Local normalization set, but df_name is None. Using global data params instead.")
            df_name = "__df__"
            if not m.config_normalization.unknown_data_normalization:
                m.config_normalization.unknown_data_normalization = True
                overwriting_unknown_data_normalization = True
        elif df_name not in m.config_normalization.local_data_params:
            log.warning(
                f"Local normalization set, but df_name '{df_name}' not found. Using global data params instead."
            )
            df_name = "__df__"
            if not m.config_normalization.unknown_data_normalization:
                m.config_normalization.unknown_data_normalization = True
                overwriting_unknown_data_normalization = True
        else:
            log.debug(f"Local normalization set. Data params for {df_name} will be used to denormalize.")

    # Identify components to be plotted
    # as dict: {plot_name, }
    components = [{"plot_name": "Trend"}]
    if m.config_trend.n_changepoints > 0:
        components.append({"plot_name": "Trend Rate Change"})

    # Plot  seasonalities, if present
    if m.config_season is not None:
        for name in m.config_season.periods:
            components.append({"plot_name": "seasonality", "comp_name": name})

    if m.n_lags > 0:
        components.append(
            {
                "plot_name": "lagged weights",
                "comp_name": "AR",
                "weights": m.model.ar_weights.detach().numpy(),
                "focus": forecast_in_focus,
            }
        )

    quantile_index = m.model.quantiles.index(quantile)

    # all scalar regressors will be plotted together
    # collected as tuples (name, weights)

    # Add Regressors
    additive_future_regressors = []
    multiplicative_future_regressors = []
    if m.config_regressors is not None:
        for regressor, configs in m.config_regressors.items():
            mode = configs.mode
            regressor_param = m.model.get_reg_weights(regressor)[quantile_index, :]
            if mode == "additive":
                additive_future_regressors.append((regressor, regressor_param.detach().numpy()))
            else:
                multiplicative_future_regressors.append((regressor, regressor_param.detach().numpy()))

    additive_events = []
    multiplicative_events = []
    # Add Events
    # add the country holidays
    if m.config_country_holidays is not None:
        for country_holiday in m.config_country_holidays.holiday_names:
            event_params = m.model.get_event_weights(country_holiday)
            weight_list = [(key, param.detach().numpy()[quantile_index, :]) for key, param in event_params.items()]
            mode = m.config_country_holidays.mode
            if mode == "additive":
                additive_events = additive_events + weight_list
            else:
                multiplicative_events = multiplicative_events + weight_list

    # add the user specified events
    if m.config_events is not None:
        for event, configs in m.config_events.items():
            event_params = m.model.get_event_weights(event)
            weight_list = [(key, param.detach().numpy()[quantile_index, :]) for key, param in event_params.items()]
            mode = configs.mode
            if mode == "additive":
                additive_events = additive_events + weight_list
            else:
                multiplicative_events = multiplicative_events + weight_list

    # Add lagged regressors
    lagged_scalar_regressors = []
    if m.config_lagged_regressors is not None:
        for name in m.config_lagged_regressors.keys():
            if m.config_lagged_regressors[name].as_scalar:
                lagged_scalar_regressors.append((name, m.model.get_covar_weights(name).detach().numpy()))
            else:
                components.append(
                    {
                        "plot_name": "lagged weights",
                        "comp_name": f'Lagged Regressor "{name}"',
                        "weights": m.model.get_covar_weights(name).detach().numpy(),
                        "focus": forecast_in_focus,
                    }
                )

    if len(additive_future_regressors) > 0:
        components.append({"plot_name": "Additive future regressor"})
    if len(multiplicative_future_regressors) > 0:
        components.append({"plot_name": "Multiplicative future regressor"})
    if len(lagged_scalar_regressors) > 0:
        components.append({"plot_name": "Lagged scalar regressor"})
    if len(additive_events) > 0:
        data_params = m.config_normalization.get_data_params(df_name)
        scale = data_params["y"].scale
        additive_events = [(key, weight * scale) for (key, weight) in additive_events]
        components.append({"plot_name": "Additive event"})
    if len(multiplicative_events) > 0:
        components.append({"plot_name": "Multiplicative event"})

    npanel = len(components)
    figsize = figsize if figsize else (10, 3 * npanel)
    fig, axes = plt.subplots(npanel, 1, facecolor="w", figsize=figsize)
    if npanel == 1:
        axes = [axes]
    multiplicative_axes = []
    for ax, comp in zip(axes, components):
        plot_name = comp["plot_name"].lower()
        if plot_name.startswith("trend"):
            if "change" in plot_name:
                plot_trend_change(m=m, quantile=quantile, ax=ax, plot_name=comp["plot_name"], df_name=df_name)
            else:
                plot_trend(m=m, quantile=quantile, ax=ax, plot_name=comp["plot_name"], df_name=df_name)
        elif plot_name.startswith("seasonality"):
            name = comp["comp_name"]
            if m.config_season.mode == "multiplicative":
                multiplicative_axes.append(ax)
            if name.lower() == "weekly" or m.config_season.periods[name].period == 7:
                plot_weekly(m=m, quantile=quantile, ax=ax, weekly_start=weekly_start, comp_name=name, df_name=df_name)
            elif name.lower() == "yearly" or m.config_season.periods[name].period == 365.25:
                plot_yearly(m=m, quantile=quantile, ax=ax, yearly_start=yearly_start, comp_name=name, df_name=df_name)
            elif name.lower() == "daily" or m.config_season.periods[name].period == 1:
                plot_daily(m=m, quantile=quantile, ax=ax, comp_name=name, df_name=df_name)
            else:
                plot_custom_season(m=m, quantile=quantile, ax=ax, comp_name=name, df_name=df_name)
        elif plot_name == "lagged weights":
            plot_lagged_weights(weights=comp["weights"], comp_name=comp["comp_name"], focus=comp["focus"], ax=ax)
        else:
            if plot_name == "additive future regressor":
                weights = additive_future_regressors
            elif plot_name == "multiplicative future regressor":
                multiplicative_axes.append(ax)
                weights = multiplicative_future_regressors
            elif plot_name == "lagged scalar regressor":
                weights = lagged_scalar_regressors
            elif plot_name == "additive event":
                weights = additive_events
            elif plot_name == "multiplicative event":
                multiplicative_axes.append(ax)
                weights = multiplicative_events
            plot_scalar_weights(weights=weights, plot_name=comp["plot_name"], focus=forecast_in_focus, ax=ax)
    fig.tight_layout()
    # Reset multiplicative axes labels after tight_layout adjustment
    for ax in multiplicative_axes:
        ax = set_y_as_percent(ax)
    if overwriting_unknown_data_normalization:
        # if overwriting_unknown_data_normalization is True, we get back to the initial False state
        m.config_normalization.unknown_data_normalization = False

    return fig


def plot_trend_change(m, quantile, ax=None, plot_name="Trend Change", figsize=(10, 6), df_name="__df__"):
    """Make a barplot of the magnitudes of trend-changes.

    Parameters
    ----------
        m : NeuralProphet
            Fitted model
        quantile : float
            The quantile for which the trend changes are plotted
        ax : matplotlib axis
            Matplotlib Axes to plot on
        plot_name : str
            Name of the plot Title
        figsize : tuple
            Width, height in inches, ignored if ax is not None.

            Note
            ----
            Default value is set to ``figsize = (10, 6)``

        df_name : str
            Name of dataframe to refer to data params from original keys of train dataframes

            Note
            ----
            Only used for local normalization in global modeling

    Returns
    -------
        matplotlib.artist.Artist
            List of Artist objects containing barplot
    """
    artists = []
    if not ax:
        fig = plt.figure(facecolor="w", figsize=figsize)
        ax = fig.add_subplot(111)
    data_params = m.config_normalization.get_data_params(df_name)
    start = data_params["ds"].shift
    scale = data_params["ds"].scale
    time_span_seconds = scale.total_seconds()
    cp_t = []
    for cp in m.model.config_trend.changepoints:
        cp_t.append(start + datetime.timedelta(seconds=cp * time_span_seconds))
    # Global/Local Mode
    if m.model.config_trend.trend_global_local == "local":
        quantile_index = m.model.quantiles.index(quantile)
        weights = m.model.get_trend_deltas.detach()[quantile_index, m.model.id_dict[df_name], :].numpy()
    else:
        quantile_index = m.model.quantiles.index(quantile)
        weights = m.model.get_trend_deltas.detach()[quantile_index, 0, :].numpy()
    # add end-point to force scale to match trend plot
    cp_t.append(start + scale)
    weights = np.append(weights, [0.0])
    width = time_span_seconds / 175000 / m.config_trend.n_changepoints
    artists += ax.bar(cp_t, weights, width=width, color="#0072B2")
    locator = AutoDateLocator(interval_multiples=False)
    formatter = AutoDateFormatter(locator)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)
    ax.grid(True, which="major", c="gray", ls="-", lw=1, alpha=0.2)
    ax.set_xlabel("Trend Segment")
    ax.set_ylabel(plot_name)
    return artists


def plot_trend(m, quantile, ax=None, plot_name="Trend", figsize=(10, 6), df_name="__df__"):
    """Make a barplot of the magnitudes of trend-changes.

    Parameters
    ----------
        m : NeuralProphet
            Fitted model
        quantile : float
            The quantile for which the trend changes are plotted
        ax : matplotlib axis
            Matplotlib Axes to plot on
        plot_name : str
            Name of the plot Title
        figsize : tuple
            Width, height in inches, ignored if ax is not None.

            Note
            ----
            Default value is set to ``figsize = (10, 6)``

        df_name : str
            Name of dataframe to refer to data params from original keys of train dataframes

            Note
            ----
            Only used for local normalization in global modeling

    Returns
    -------
        matplotlib.artist.Artist
            List of Artist objects containing barplot
    """
    artists = []
    if not ax:
        fig = plt.figure(facecolor="w", figsize=figsize)
        ax = fig.add_subplot(111)
    data_params = m.config_normalization.get_data_params(df_name)
    t_start = data_params["ds"].shift
    t_end = t_start + data_params["ds"].scale
    quantile_index = m.model.quantiles.index(quantile)
    if m.config_trend.n_changepoints == 0:
        fcst_t = pd.Series([t_start, t_end]).dt.to_pydatetime()
        trend_0 = m.model.bias[quantile_index].detach().numpy().squeeze()
        if m.config_trend.growth == "off":
            trend_1 = trend_0
        else:
            if m.model.config_trend.trend_global_local == "local":
                trend_1 = trend_0 + m.model.trend_k0[quantile_index, m.model.id_dict[df_name]].detach().numpy()
            else:
                trend_1 = trend_0 + m.model.trend_k0[quantile_index, 0].detach().numpy()

        data_params = m.config_normalization.get_data_params(df_name)
        shift = data_params["y"].shift
        scale = data_params["y"].scale
        trend_0 = trend_0 * scale + shift
        trend_1 = trend_1 * scale + shift
        artists += ax.plot(fcst_t, [trend_0, trend_1], ls="-", c="#0072B2")
    else:
        days = pd.date_range(start=t_start, end=t_end, freq=m.data_freq)
        df_y = pd.DataFrame({"ds": days})
        df_y["ID"] = df_name
        df_trend = m.predict_trend(df=df_y, quantile=quantile)
        artists += ax.plot(df_y["ds"].dt.to_pydatetime(), df_trend["trend"], ls="-", c="#0072B2")
    # Specify formatting to workaround matplotlib issue #12925
    locator = AutoDateLocator(interval_multiples=False)
    formatter = AutoDateFormatter(locator)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)
    ax.grid(True, which="major", c="gray", ls="-", lw=1, alpha=0.2)
    ax.set_xlabel("ds")
    ax.set_ylabel(plot_name)
    return artists


def plot_scalar_weights(weights, plot_name, focus=None, ax=None, figsize=(10, 6)):
    """Make a barplot of the regressor weights.

    Parameters
    ----------
        weights : list
            tuples of (name, weights)
        plot_name : str
            Name of the plot Title
        focus : int
            Show weights for this forecast, if provided
        ax : matplotlib axis
            Matplotlib Axes to plot on
        figsize : tuple
            Width, height in inches, ignored if ax is not None.

            Note
            ----
            Default value is set to ``figsize = (10, 6)``

    Returns
    -------
        matplotlib.artist.Artist
            List of Artist objects containing barplot
    """
    artists = []
    if not ax:
        fig = plt.figure(facecolor="w", figsize=figsize)
        ax = fig.add_subplot(111)
    # if len(regressors) == 1:
    # else:
    names = []
    values = []
    for name, weights in weights:
        names.append(name)
        weight = np.squeeze(weights)
        if len(weight.shape) > 1:
            raise ValueError("Not scalar " + plot_name)
        if len(weight.shape) == 1 and len(weight) > 1:
            if focus is not None:
                weight = weight[focus - 1]
            else:
                weight = np.mean(weight)
        values.append(weight)
    artists += ax.bar(names, values, width=0.8, color="#0072B2")
    ax.grid(True, which="major", c="gray", ls="-", lw=1, alpha=0.2)
    ax.set_xlabel(plot_name + " name")
    xticks = ax.get_xticklabels()
    if len("_".join(names)) > 100:
        for tick in xticks:
            tick.set_ha("right")
            tick.set_rotation(20)
    if "lagged" in plot_name.lower():
        if focus is None:
            ax.set_ylabel(plot_name + " weight (avg)")
        else:
            ax.set_ylabel(plot_name + f" weight ({focus})-ahead")
    else:
        ax.set_ylabel(plot_name + " weight")
    return artists


def plot_lagged_weights(weights, comp_name, focus=None, ax=None, figsize=(10, 6)):
    """Make a barplot of the importance of lagged inputs.

    Parameters
    ----------
        weights : list
            tuples of (name, weights)
        comp_name : str
            Name of lagged inputs
        focus : int
            Show weights for this forecast, if provided
        ax : matplotlib axis
            Matplotlib Axes to plot on
        figsize : tuple
            Width, height in inches, ignored if ax is not None.

            Note
            ----
            Default value is set to ``figsize = (10, 6)``

    Returns
    -------
        matplotlib.artist.Artist
            List of Artist objects containing barplot
    """
    artists = []
    if not ax:
        fig = plt.figure(facecolor="w", figsize=figsize)
        ax = fig.add_subplot(111)
    n_lags = weights.shape[1]
    lags_range = list(range(1, 1 + n_lags))[::-1]
    if focus is None:
        weights = np.sum(np.abs(weights), axis=0)
        weights = weights / np.sum(weights)
        artists += ax.bar(lags_range, weights, width=1.00, color="#0072B2")
    else:
        if len(weights.shape) == 2:
            weights = weights[focus - 1, :]
        artists += ax.bar(lags_range, weights, width=0.80, color="#0072B2")
    ax.grid(True, which="major", c="gray", ls="-", lw=1, alpha=0.2)
    ax.set_xlabel(f"{comp_name} lag number")
    if focus is None:
        ax.set_ylabel(f"{comp_name} relevance")
        ax = set_y_as_percent(ax)
    else:
        ax.set_ylabel(f"{comp_name} weight ({focus})-ahead")
    return artists


def predict_one_season(m, quantile, name, n_steps=100, df_name="__df__"):
    config = m.config_season.periods[name]
    t_i = np.arange(n_steps + 1) / float(n_steps)
    features = time_dataset.fourier_series_t(
        t=t_i * config.period, period=config.period, series_order=config.resolution
    )
    features = torch.from_numpy(np.expand_dims(features, 1))

    if df_name == "__df__":
        meta_name_tensor = None
    else:
        meta = OrderedDict()
        meta["df_name"] = [df_name for _ in range(n_steps + 1)]
        meta_name_tensor = torch.tensor([m.model.id_dict[i] for i in meta["df_name"]])

    quantile_index = m.model.quantiles.index(quantile)
    predicted = m.model.seasonality(features=features, name=name, meta=meta_name_tensor)[:, :, quantile_index]
    predicted = predicted.squeeze().detach().numpy()
    if m.config_season.mode == "additive":
        data_params = m.config_normalization.get_data_params(df_name)
        scale = data_params["y"].scale
        predicted = predicted * scale
    return t_i, predicted


def predict_season_from_dates(m, dates, name, quantile, df_name="__df__"):
    config = m.config_season.periods[name]
    features = time_dataset.fourier_series(dates=dates, period=config.period, series_order=config.resolution)
    features = torch.from_numpy(np.expand_dims(features, 1))
    if df_name == "__df__":
        meta_name_tensor = None
    else:
        meta = OrderedDict()
        meta["df_name"] = [df_name for _ in range(len(dates))]
        meta_name_tensor = torch.tensor([m.model.id_dict[i] for i in meta["df_name"]])

    quantile_index = m.model.quantiles.index(quantile)
    predicted = m.model.seasonality(features=features, name=name, meta=meta_name_tensor)[:, :, quantile_index]

    predicted = predicted.squeeze().detach().numpy()
    if m.config_season.mode == "additive":
        data_params = m.config_normalization.get_data_params(df_name)
        scale = data_params["y"].scale
        predicted = predicted * scale
    return predicted


def plot_custom_season(m, comp_name, quantile, ax=None, figsize=(10, 6), df_name="__df__"):
    """Plot any seasonal component of the forecast.

    Parameters
    ----------
        m : NeuralProphet
            Fitted model
        comp_name : str
            Name of seasonality component
        quantile : float
            The quantile for which the custom season is plotted
        ax : matplotlib axis
            Matplotlib Axes to plot on
        focus : int
            Show weights for this forecast, if provided
        figsize : tuple
            Width, height in inches, ignored if ax is not None.

            Note
            ----
            Default value is set to ``figsize = (10, 6)``
        df_name : str
            Name of dataframe to refer to data params from original keys of train dataframes

            Note
            ----
            Only used for local normalization in global modeling

    Returns
    -------
        matplotlib.artist.Artist
            List of Artist objects containing seasonal forecast component

    """
    t_i, predicted = predict_one_season(m, name=comp_name, n_steps=300, quantile=quantile, df_name=df_name)
    artists = []
    if not ax:
        fig = plt.figure(facecolor="w", figsize=figsize)
        ax = fig.add_subplot(111)
    artists += ax.plot(t_i, predicted, ls="-", c="#0072B2")
    ax.grid(True, which="major", c="gray", ls="-", lw=1, alpha=0.2)
    ax.set_xlabel(f"One period: {comp_name}")
    ax.set_ylabel(f"Seasonality: {comp_name}")
    return artists


def plot_yearly(
    m, quantile, comp_name="yearly", yearly_start=0, quick=True, ax=None, figsize=(10, 6), df_name="__df__"
):
    """Plot the yearly component of the forecast.

    Parameters
    ----------
        m : NeuralProphet
            Fitted model
        quantile : float
            The quantile for which the yearly seasonality is plotted
        comp_name : str
            Name of seasonality component
        yearly_start : int
            Specifying the start day of the yearly seasonality plot

            Options
                * (default) ``yearly_start = 0``: starts the year on Jan 1
                * ``yearly_start = 1``: shifts by 1 day to Jan 2, and so on
        quick : bool
            Use quick low-level call of model
        ax : matplotlib axis
            Matplotlib Axes to plot on
        figsize : tuple
            Width, height in inches, ignored if ax is not None.

            Note
            ----
            Default value is set to ``figsize = (10, 6)``
        df_name : str
            Name of dataframe to refer to data params from original keys of train dataframes

            Note
            ----
            Only used for local normalization in global modeling

    Returns
    -------
        matplotlib.artist.Artist
            List of Artist objects containing yearly forecast component

    """
    artists = []
    if not ax:
        fig = plt.figure(facecolor="w", figsize=figsize)
        ax = fig.add_subplot(111)
    # Compute yearly seasonality for a Jan 1 - Dec 31 sequence of dates.
    days = pd.date_range(start="2017-01-01", periods=365) + pd.Timedelta(days=yearly_start)
    df_y = pd.DataFrame({"ds": days})
    if quick:
        predicted = predict_season_from_dates(m, dates=df_y["ds"], name=comp_name, quantile=quantile, df_name=df_name)
    else:
        predicted = m.predict_seasonal_components({df_name: df_y}, quantile=quantile)[comp_name]
    artists += ax.plot(df_y["ds"].dt.to_pydatetime(), predicted, ls="-", c="#0072B2")
    ax.grid(True, which="major", c="gray", ls="-", lw=1, alpha=0.2)
    months = MonthLocator(range(1, 13), bymonthday=1, interval=2)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, pos=None: f"{num2date(x):%B} {num2date(x).day}"))
    ax.xaxis.set_major_locator(months)
    ax.set_xlabel("Day of year")
    ax.set_ylabel(f"Seasonality: {comp_name}")
    return artists


def plot_weekly(
    m, quantile, comp_name="weekly", weekly_start=0, quick=True, ax=None, figsize=(10, 6), df_name="__df__"
):
    """Plot the weekly component of the forecast.

    Parameters
    ----------
        m : NeuralProphet
            Fitted model
        quantile : float
            The quantile for which the weekly seasonality is plotted
        comp_name : str
            Name of seasonality component
        weekly_start : int
            Specifying the start day of the weekly seasonality plot

            Options
                * (default) ``weekly_start = 0``: starts the week on Sunday
                * ``weekly_start = 1``: shifts by 1 day to Monday, and so on
        quick : bool
            Use quick low-level call of model
        ax : matplotlib axis
            Matplotlib Axes to plot on
        figsize : tuple
            Width, height in inches, ignored if ax is not None.

            Note
            ----
            Default value is set to ``figsize = (10, 6)``
        df_name : str
            Name of dataframe to refer to data params from original keys of train dataframes

            Note
            ----
            Only used for local normalization in global modeling

    Returns
    -------
        matplotlib.artist.Artist
            List of Artist objects containing weekly forecast component

    """
    artists = []
    if not ax:
        fig = plt.figure(facecolor="w", figsize=figsize)
        ax = fig.add_subplot(111)
    # Compute weekly seasonality for a Sun-Sat sequence of dates.
    days_i = pd.date_range(start="2017-01-01", periods=7 * 24, freq="H") + pd.Timedelta(days=weekly_start)
    df_w = pd.DataFrame({"ds": days_i})
    if quick:
        predicted = predict_season_from_dates(m, dates=df_w["ds"], name=comp_name, quantile=quantile, df_name=df_name)
    else:
        predicted = m.predict_seasonal_components({df_name: df_w}, quantile=quantile)[comp_name]
    days = pd.date_range(start="2017-01-01", periods=7) + pd.Timedelta(days=weekly_start)
    days = days.day_name()
    artists += ax.plot(range(len(days_i)), predicted, ls="-", c="#0072B2")
    ax.grid(True, which="major", c="gray", ls="-", lw=1, alpha=0.2)
    ax.set_xticks(24 * np.arange(len(days) + 1))
    ax.set_xticklabels(list(days) + [days[0]])
    ax.set_xlabel("Day of week")
    ax.set_ylabel(f"Seasonality: {comp_name}")
    return artists


def plot_daily(m, quantile, comp_name="daily", quick=True, ax=None, figsize=(10, 6), df_name="__df__"):
    """Plot the daily component of the forecast.

    Parameters
    ----------
        m : NeuralProphet
            Fitted model
        quantile : float
            The quantile for which the daily seasonality is plotted
        comp_name : str
            Name of seasonality component if previously changed from default ``daily``
        quick : bool
            Use quick low-level call of model
        ax : matplotlib axis
            Matplotlib Axes to plot on
        figsize : tuple
            Width, height in inches, ignored if ax is not None.

            Note
            ----
            Default value is set to ``figsize = (10, 6)``
        df_name : str
            Name of dataframe to refer to data params from original keys of train dataframes

            Note
            ----
            Only used for local normalization in global modeling

    Returns
    -------
        matplotlib.artist.Artist
            List of Artist objects containing weekly forecast component
    """
    artists = []
    if not ax:
        fig = plt.figure(facecolor="w", figsize=figsize)
        ax = fig.add_subplot(111)
    # Compute daily seasonality
    dates = pd.date_range(start="2017-01-01", periods=24 * 12, freq="5min")
    df = pd.DataFrame({"ds": dates})
    if quick:
        predicted = predict_season_from_dates(m, dates=df["ds"], name=comp_name, quantile=quantile, df_name=df_name)
    else:
        predicted = m.predict_seasonal_components({df_name: df}, quantile=quantile)[comp_name]
    artists += ax.plot(range(len(dates)), predicted, ls="-", c="#0072B2")
    ax.grid(True, which="major", c="gray", ls="-", lw=1, alpha=0.2)
    ax.set_xticks(12 * np.arange(25))
    ax.set_xticklabels(np.arange(25))
    ax.set_xlabel("Hour of day")
    ax.set_ylabel(f"Seasonality: {comp_name}")
    return artists
