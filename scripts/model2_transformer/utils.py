import logging
logging.disable(logging.WARNING)
import warnings 
warnings.filterwarnings("ignore")
import torch
import pickle
from transformers import BertModel, BertConfig
from DNABERT_v1.src.transformers import DNATokenizer
import csv
import re
from pathlib import Path
import os
import tarfile
import shutil
import json
import sys
import pandas as pd
import random
import numpy as np
import glob
import math

kmer = 6
dir_to_pretrained_model = '/new-stg/home/cong/DPI/DNABERT/pretrained/'+str(kmer)+'-new-12w-0/'
path_to_config = '/new-stg/home/cong/DPI/DNABERT/src/transformers/dnabert-config/bert-config-'+str(kmer)+'/config.json'
path_to_token = '/new-stg/home/cong/DPI/DNABERT/src/transformers/dnabert-config/bert-config-'+str(kmer)+'/vocab.txt'

config = BertConfig.from_pretrained(path_to_config)
tokenizer = DNATokenizer.from_pretrained(path_to_token)
model = BertModel.from_pretrained(dir_to_pretrained_model, config=config)


# prepare for dataset loading
protein_emb_dir = "/new-stg/home/cong/DPI/colabfold/output/uniprot-download_Encode3_fasta-2022.11.17-18.19.17.82/"

# loading mapping file to convert between gene name and uniprot id just in case
mapping_file = '/new-stg/home/cong/DPI/downloads/HUMAN_9606_idmapping.dat'
mapping_df = pd.read_csv(mapping_file,sep="\t",header=None,names=['id','cat','name'])
mapping_df = mapping_df[mapping_df['cat'].isin(['Gene_Name','Gene_Synonym'])]


def get_DNA_embedding(row,kmer):
    sequence = row['dna']
    sequence = ' '.join([sequence[i:i+kmer] for i in range(0, (len(sequence)-kmer+1))])
#     print(sequence)
    with torch.no_grad():
        model_input = tokenizer.encode_plus(sequence, add_special_tokens=True, max_length=512, truncation=True)["input_ids"]
        model_input = torch.tensor(model_input, dtype=torch.long)
        model_input = model_input.unsqueeze(0)   # to generate a fake batch with batch size one
#         print(model_input)
        output = model(model_input)

    embed = output[0]
    embed = torch.squeeze(embed)
#     embed = embed.numpy()
#     embed = np.mean(embed, axis=1)
    print("embedding size is "+ str(embed.shape))
#     print("embedding mean is " + str(torch.mean(embed,0)[0:10]))
#     print(embed)
    return embed


def gene_name_to_id(gene_name,mapping_df):
    return mapping_df[mapping_df['name'].str.upper()==gene_name]['id'].tolist()

def pick_single_protein_pickle(fileL):
    """
    pick one file from an unempty list of files
    """
    if len(fileL)>1:
        file = random.sample(fileL,1)[0]
    else:
        file = fileL[0]
    return file

def protein2emb(row):
    pro = row['protein']
    fileL = glob.glob(protein_emb_dir+'*'+pro+'*single_repr*npy', recursive=True)
    if len(fileL)>=1:
        file = pick_single_protein_pickle(fileL)
    # other situations that the file name contains gene synonym
    else:
        idL = gene_name_to_id(pro,mapping_df)
        for id in idL: 
            fileL = glob.glob(protein_emb_dir+'*'+id+'*single_repr*npy', recursive=True)
            if len(fileL) >= 1:
                file = pick_single_protein_pickle(fileL)
            break
    try:
        x = np.load(file)    
        print("protein embedding size is "+str(x.shape))
        return x
    except:
        print(pro,"doesn't have embedding, returns an empty list")
        return None

def add_two_columns(df):
    """
    add dna_embedding and protein_embedding as two columns to df
    """
    col = df.apply(get_DNA_embedding, axis=1, kmer=kmer) 
    df = df.assign(dna_embedding=col.values)
    
    col = df.apply(protein2emb, axis=1) 
    df = df.assign(protein_embedding=col.values)
    df = df.dropna()
#     df[df['protein_embedding'].map(lambda d: len(d)) > 0]
    return df


def unify_dim_embedding(x,crop_size):
    """
    crops/pads embedding to unify the dimention implementing AlphaFold's cropping strategy

    :param x: protein or dna embedding (seq_length,) or (seq_length,emb_size)
    :type x: numpy.ndarray
    :param crop_size: crop size, either max_p or max_d
    :type crop_size: int
    :return x: unified embedding (crop_size,)
    :type x: numpy.ndarray

    """
    pad_token_index = 0
    seq_length = x.shape[0]
    if seq_length < crop_size:
        input_mask = ([1] * seq_length) + ([0] * (crop_size - seq_length))
        if x.ndim == 1:
            x = torch.from_numpy(np.pad(x, (0, crop_size - seq_length), 'constant', constant_values = pad_token_index))
        elif x.ndim == 2:
            x = torch.from_numpy(np.pad(x, ((0, crop_size - seq_length),(0,0)), 'constant', constant_values = pad_token_index))
    else:
        start_pos = random.randint(0,seq_length-crop_size)
        x = x[start_pos:start_pos+crop_size]
        if isinstance(x, np.ndarray):
#         if not torch.is_tensor(x):
            x = torch.from_numpy(x)
        input_mask = [1] * crop_size
    return x, np.asarray(input_mask)

