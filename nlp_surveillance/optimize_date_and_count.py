import pickle
import os
import numpy as np
import pandas as pd
import urllib.error
from datetime import datetime
from tqdm import tqdm_notebook as tqdm

from .utils.my_utils import (remove_nans,
                             check_url_validity,
                             remove_guillemets,
                             split_and_flatten_list,
                             get_sentence_and_date_from_annotated_span)
from .utils.text_from_url import extract_cleaned_text_from_url
from .edb_clean import get_cleaned_edb
from .annotator import annotate


def get_date_optimization_edb(edb=None):
    if edb is None:
        edb = get_cleaned_edb()

    edb_links_combined = _get_edb_with_combined_link_columns(edb)
    date_optimization_edb = _get_optimization_edb(edb_links_combined, to_optimize='date')
    date_optimization_edb_extracted_text = _extract_text_from_edb_urls(date_optimization_edb)
    date_optimization_edb_with_annos = _annotate_text_in_edb(date_optimization_edb_extracted_text)
    date_optimization_edb_extracted_sentences = _extract_sentences_from_spans(date_optimization_edb_with_annos)
    return date_optimization_edb_with_annos


def _get_edb_with_combined_link_columns(edb):
    link_columns = [column for column in edb.columns.tolist() if 'link' in column.lower()]
    edb_with_any_link = edb[link_columns].dropna(how='all')
    urls = edb_with_any_link.apply(lambda x: list(split_and_flatten_list(x)), axis=1)
    edb_links_combined = edb.drop(link_columns, axis=1)
    edb_links_combined['links'] = pd.Series(list(map(lambda x: split_and_flatten_list(x), urls)))
    return _remove_invalid_urls(edb_links_combined)


def _get_optimization_edb(edb, to_optimize):
    # Data Frame for date or count?
    if to_optimize == 'date':
        edb = edb[edb['Datenstand für Fallzahlen gesamt*'].notna()]
        edb = edb[['Datenstand für Fallzahlen gesamt*', 'links']]
        edb['Datenstand für Fallzahlen gesamt*'] = edb['Datenstand für Fallzahlen gesamt*'].apply(
                                                        lambda x: datetime.strptime(x, '%Y-%m-%d'))
    else:
        edb = edb  # placeholder for count optimized edb
    return edb


def _extract_text_from_edb_urls(edb, disable_tqdm=False):
    # TODO: think about a test for this function
    file_dir = os.path.dirname(__file__)
    path = os.path.join(file_dir, 'pickles', 'edb_with_text.p')
    if not os.path.exists(path):
        edb_with_text = pd.DataFrame(columns=['Datenstand für Fallzahlen gesamt*', 'links', 'text'])
        for i, urls in enumerate(tqdm(edb['links'], disable=disable_tqdm)):
            for j, url in enumerate(urls):
                edb_with_text = _try_to_extract_text_from_url_and_fill_edb_with_text(edb, edb_with_text, url, i)
        pickle.dump(edb_with_text, open(path, 'wb'))
    else:
        edb_with_text = pickle.load(open(path, 'rb'))
    return edb_with_text


def _annotate_text_in_edb(edb):
    annos = pd.Series(np.zeros(len(edb)))
    for i, text in enumerate(tqdm(edb['text'])):
        annotated = annotate(text, tiers='DateAnnotator()')
        annos.loc[i] = annotated
    edb['annotated'] = annos
    return edb


def _extract_sentences_from_spans(edb, drop_annotated=True):
    edb_with_sentences = pd.DataFrame(columns=['Datenstand für Fallzahlen gesamt*',
                                               'date_from_sentence',
                                               'sentence'])
    for i, row in tqdm(edb[['Datenstand für Fallzahlen gesamt*', 'text', 'annotated']].iterrows(), total=edb.shape[0]):
        target_date, text, anno = row
        for span in anno.tiers['dates'].spans:
            try:
                sentence, date_in_sentence = get_sentence_and_date_from_annotated_span(span, text)
            except AttributeError:
                sentence, date_in_sentence = (np.nan, np.nan)
            to_append = pd.Series({'Datenstand für Fallzahlen gesamt*': target_date,
                                   'date_from_sentence': date_in_sentence,
                                   'sentence': sentence})
            edb_with_sentences = edb_with_sentences.append(to_append, ignore_index=True)
    if not drop_annotated:
        edb_with_sentences['annotated'] = edb['annotated'] # AnnoDocs cannot be pickled, so I drop them
    return edb_with_sentences


def _try_extract_sentences(text, date_span):
    try:
        date_sentences = get_sentence_and_date_from_annotated_span(date_span, text)
    except AttributeError:
        date_sentences = []  # Occurs when sentences is empty
    return date_sentences


def _try_to_extract_text_from_url_and_fill_edb_with_text(edb, edb_with_text, url, i):
    try:
        text_extracted = extract_cleaned_text_from_url(url)
        date = edb['Datenstand für Fallzahlen gesamt*'].iloc[i]
        to_append = pd.Series({'Datenstand für Fallzahlen gesamt*': date,
                               'links': url,
                               'text': text_extracted})
        edb_with_text = edb_with_text.append(to_append, ignore_index=True)
    except (ConnectionResetError, urllib.error.HTTPError):
        print(url, 'caused ConnectionResetError')
    return edb_with_text


def _remove_invalid_urls(edb):
    # Valid URL
    edb['links'] = edb['links'].apply(remove_nans)
    edb['links'] = edb['links'].apply(_only_keep_valid_urls)
    valid_target_and_example_edb = edb.reset_index(drop=True)
    return valid_target_and_example_edb


def _create_new_row(date, link, text_extracted):
    return pd.Series({'Datenstand für Fallzahlen gesamt*': date,
                      'links': link,
                      'text': text_extracted})


def _only_keep_valid_urls(list_of_urls):
    removed_guillemets = map(remove_guillemets, list_of_urls)
    valid_urls = filter(check_url_validity, removed_guillemets)
    return list(valid_urls)
