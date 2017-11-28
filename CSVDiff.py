#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  CSVDiff.py
#  csvdiff
#




from __future__ import absolute_import, print_function, division,unicode_literals
import json
import sys
from operator import itemgetter
import click
import os
from os import listdir

from os.path import isfile, join
from CSVDiff import patch, records, error
from Web.matchLayout import matchLayout

dir='CSVdiff/finalLayouts/RX_LAYOUTS/'
singleFile1="rx_layout20.csv"
singleFile2="rx_layout55.csv"

from_records_ct=0
to_records_ct=0
if sys.version_info.major == 2:
    import StringIO as io
else:
    import io

# exit codes for the command-line
EXIT_SAME = 0
EXIT_DIFFERENT = 1
EXIT_ERROR = 2

def diff_files(from_file, to_file, index_columns, sep=',', ignored_columns=None):
    """
    Diff two CSV files, returning the patch which transforms one into the
    other.
    """
    with open(from_file) as from_stream:
        with open(to_file) as to_stream:
            from_records = records.load(from_stream, sep=sep)
            to_records = records.load(to_stream, sep=sep)
            # a=list(from_records)
            # print(a)
            # if abs(from_records.reader.line_num - to_records.reader.line_num) > 20:
            #     return False
            return patch.create(from_records, to_records, index_columns,
                                ignore_columns=ignored_columns)


def diff_records(from_records, to_records, index_columns):
    """
    Diff two sequences of dictionary records, returning the patch which
    transforms one into the other.
    """
    return patch.create(from_records, to_records, index_columns)


def patch_file(patch_stream, fromcsv_stream, tocsv_stream, strict=True,
               sep=','):
    """
    Apply the patch to the source CSV file, and save the result to the target
    file.
    """
    diff = patch.load(patch_stream)

    from_records = records.load(fromcsv_stream, sep=sep)
    to_records = patch.apply(diff, from_records, strict=strict)

    # what order should the columns be in?
    if to_records:
        # have data, use a nice ordering
        all_columns = to_records[0].keys()
        index_columns = diff['_index']
        fieldnames = _nice_fieldnames(all_columns, index_columns)
    else:
        # no data, use the original order
        fieldnames = from_records.fieldnames

    records.save(to_records, fieldnames, tocsv_stream)


def patch_records(diff, from_records, strict=True):
    """
    Apply the patch to the sequence of records, returning the transformed
    records.
    """
    return patch.apply(diff, from_records, strict=strict)


def _nice_fieldnames(all_columns, index_columns):
    "Indexes on the left, other fields in alphabetical order on the right."
    non_index_columns = set(all_columns).difference(index_columns)
    return index_columns + sorted(non_index_columns)


class CSVType(click.ParamType):
    name = 'csv'

    def convert(self, value, param, ctx):
        if isinstance(value, bytes):
            try:
                enc = getattr(sys.stdin, 'encoding', None)
                if enc is not None:
                    value = value.decode(enc)
            except UnicodeError:
                try:
                    value = value.decode(sys.getfilesystemencoding())
                except UnicodeError:
                    value = value.decode('utf-8', 'replace')
            return value.split(',')

        return value.split(',')

    def __repr__(self):
        return 'CSV'


@click.command()
@click.argument('index_columns', type=CSVType())
@click.argument('from_csv', type=click.Path(exists=True))
@click.argument('to_csv', type=click.Path(exists=True))
@click.option('--style',
              type=click.Choice(['compact', 'pretty', 'summary']),
              default='compact',
              help=('Instead of the default compact output, pretty-print '
                    'or give a summary instead'))
@click.option('--output', '-o', type=click.Path(),
              help='Output to a file instead of stdout')
@click.option('--quiet', '-q', is_flag=True,
              help="Don't output anything, just use exit codes")
@click.option('--sep', default=',',
              help='Separator to use between fields [default: comma]')
@click.option('--ignore-columns', '-i', type=CSVType(),
              help='a comma seperated list of columns to ignore from the comparison')
@click.option('--significance', type=int,
              help='Ignore numeric changes less than this number of significant figures')
def csvdiff_cmd(index_columns, from_csv, to_csv, style=None, output=None,
                sep=',', quiet=False, ignore_columns=None, significance=None):
    """
    Compare two csv files to see what rows differ between them. The files
    are each expected to have a header row, and for each row to be uniquely
    identified by one or more indexing columns.
    """

    if ignore_columns is not None:
        for i in ignore_columns:
            if i in index_columns:
                error.abort("You can't ignore an index column")

    ostream = (open(output, 'w') if output
               else io.StringIO() if quiet
    else sys.stdout)

    try:
        if style == 'summary':
            _diff_and_summarize(from_csv, to_csv, index_columns, ostream,
                                sep=sep, ignored_columns=ignore_columns,
                                significance=significance)
        else:
            compact = (style == 'compact')
            _diff_files_to_stream(from_csv, to_csv, index_columns, ostream,
                                  compact=compact, sep=sep, ignored_columns=ignore_columns,
                                  significance=significance)

    except records.InvalidKeyError as e:
        error.abort(e.args[0])

    finally:
        ostream.close()


def _diff_files_to_stream(from_csv, to_csv, index_columns, ostream,
                          compact=False, sep=',', ignored_columns=None,
                          significance=None):
    diff = diff_files(from_csv, to_csv, index_columns, sep=sep, ignored_columns=ignored_columns)
    if diff == False:
        return 0
    if significance is not None:
        diff = patch.filter_significance(diff, significance)

    patch.save(diff, ostream, compact=compact)


def _diff_and_summarize(from_csv, to_csv, index_columns, stream=sys.stdout,
                        sep=',', ignored_columns=None, significance=None):
    """
    Print a summary of the difference between the two files.
    """
    from_records = list(records.load(from_csv, sep=sep))
    to_records = records.load(to_csv, sep=sep)

    diff = patch.create(from_records, to_records, index_columns, ignored_columns)
    if significance is not None:
        diff = patch.filter_significance(diff, significance)

    _summarize_diff(diff, len(from_records), stream=stream)
    exit_code = (EXIT_SAME
                 if patch.is_empty(diff)
                 else EXIT_DIFFERENT)
    sys.exit(exit_code)


def _summarize_diff(diff, orig_size, stream=sys.stdout):
    if orig_size == 0:
        # slightly arbitrary when the original data was empty
        orig_size = 1

    n_removed = len(diff['removed'])
    n_added = len(diff['added'])
    n_changed = len(diff['changed'])

    if n_removed or n_added or n_changed:
        print(u'%d rows removed (%.01f%%)' % (
            n_removed, 100 * n_removed / orig_size
        ), file=stream)
        print(u'%d rows added (%.01f%%)' % (
            n_added, 100 * n_added / orig_size
        ), file=stream)
        print(u'%d rows changed (%.01f%%)' % (
            n_changed, 100 * n_changed / orig_size
        ), file=stream)
    else:
        print(u'files are identical', file=stream)


@click.command()
@click.argument('input_csv', type=click.Path(exists=True))
@click.option('--input', '-i', type=click.Path(exists=True),
              help='Read the JSON patch from the given file.')
@click.option('--output', '-o', type=click.Path(),
              help='Write the transformed CSV to the given file.')
@click.option('--strict/--no-strict', default=True,
              help='Whether or not to tolerate a changed source document '
                   '(default: strict)')
def csvpatch_cmd(input_csv, input=None, output=None, strict=True):
    """
    Apply the changes from a csvdiff patch to an existing CSV file.
    """
    patch_stream = (sys.stdin
                    if input is None
                    else open(input))
    tocsv_stream = (sys.stdout
                    if output is None
                    else open(output, 'w'))
    fromcsv_stream = open(input_csv)

    try:
        patch_file(patch_stream, fromcsv_stream, tocsv_stream, strict=strict)

    except patch.InvalidPatchError as e:
        error.abort('reading patch, {0}'.format(e.args[0]))

    finally:
        patch_stream.close()
        fromcsv_stream.close()
        tocsv_stream.close()


def getAccruacy(from_records_ct, to_records_ct, weightList):

    finalWeight = 0.3*sum(weightList) / len(weightList)
    numberOne = 0.4*weightList.count(1.0)/len(weightList)
    a=from_records_ct/to_records_ct if from_records_ct/to_records_ct <1 else to_records_ct/from_records_ct
    third=a*0.3

    return finalWeight+numberOne+third

def runAll(tocheck):
    onlyfiles = [f for f in listdir(dir)]
    maxsimilarity=[]
    for file in onlyfiles:
        filename=file.replace('.csv','.json')
        val = _diff_files_to_stream(dir+tocheck,
                                    dir + file, index_columns=['COLUMNNAME'],
                                    ostream=open('Layout_Output/'+tocheck.replace('.csv','_')+file.replace('.csv','.json'), 'w'),
                                    ignored_columns=['SUBLAYOUTID', 'COLUMNID', 'DATETYPEDETIAL', 'FIELDLENGTH', 'SN',
                                                     'STARTPOS', 'ENDPOS', 'UPDATED_BY', 'FIELDLINENUMBER',
                                                     'FIELDDELIMITER', 'FIELDPOSITION', 'CATEGORY', 'BUSINESSNAME',
                                                     'SEMANTICKEY'])

        if val == 0:
            with open("log" + ".txt", "a") as myfile:
                myfile.write(tocheck + " " + file + " " + "0\n")
            #print(tocheck,file, 0)
        else:
            from_records = list(records.load(dir+tocheck, ','))
            to_records = list(records.load(dir + file, ','))
            value=getAccruacy(len(from_records), len(to_records), patch.weightList)
            maxsimilarity.append((file,tocheck,value))
            #print(tocheck,file,value)
            with open("log" + ".txt", "a") as myfile:
                myfile.write(tocheck + " " + file + " " + str(value) + "\n")
            added = []
            removed = []
            # '+file.split('.csv
            # ')[0]+'

            with open('Layout_Output/'+tocheck.replace('.csv','_')+file.replace('.csv','.json')) as data_file:
                data = json.load(data_file)
            for each_data in data['added']:
                added.append(each_data['COLUMNNAME'])

            for each_data in data['removed']:
                removed.append(each_data['COLUMNNAME'])


        patch.weightList = []


    showSimilarity(maxsimilarity)

def showSimilarity(maxSimilarity):
    calculated= (sorted(maxSimilarity,key=itemgetter(2),reverse=True)[:5])
    json_value={
        "inputFileName":[x[1] for x in calculated],
        "filename":[x[0] for x in calculated],
        "similarity":[x[2] for x in calculated]
    }
    with open("top5Output"+".txt", "a") as myfile:
        myfile.write(json.dumps(json_value)+"\n")

def runSingle():
    #onlyfiles = [f for f in listdir('CSVdiff/layouts_data/RX_LAYOUTS')]
    similarity = ""
    val = _diff_files_to_stream(dir+singleFile1,
                                dir+singleFile2, index_columns=['COLUMNNAME'],
                                ostream=open('output.json', 'w'),
                                ignored_columns=['SUBLAYOUTID', 'COLUMNID','DATETYPEDETIAL','FIELDLENGTH','SN','STARTPOS','ENDPOS','UPDATED_BY','FIELDLINENUMBER','FIELDDELIMITER','FIELDPOSITION','CATEGORY','BUSINESSNAME','SEMANTICKEY'])

    if val  != 0:
        from_records = list(records.load(dir+singleFile1, ','))
        to_records = list(records.load(dir + singleFile2, ','))
        similarity = getAccruacy(len(from_records), len(to_records), patch.weightList)
        print(singleFile1, similarity)
        added = []
        removed = []
        with open('output.json') as data_file:
            data = json.load(data_file)
        for each_data in data['added']:
            added.append(each_data['COLUMNNAME'])
        for each_data in data['removed']:
            removed.append(each_data['COLUMNNAME'])
    else:
        print("Difference in length of record is large")
    return similarity

def runSingleInAll():
    onlyfiles = [f for f in listdir(dir)]
    maxsimilarity = []
    for file in onlyfiles:
        filename = file.replace('.csv', '.json')
        val = _diff_files_to_stream(dir + singleFile1,
                                    dir + file, index_columns=['COLUMNNAME'],
                                    ostream=open(
                                        'Layout_Output/' + singleFile1.replace('.csv', '_') + file.replace('.csv', '.json'),
                                        'w'),
                                    ignored_columns=['SUBLAYOUTID', 'COLUMNID', 'DATETYPEDETIAL', 'FIELDLENGTH', 'SN',
                                                     'STARTPOS', 'ENDPOS', 'UPDATED_BY', 'FIELDLINENUMBER',
                                                     'FIELDDELIMITER', 'FIELDPOSITION', 'CATEGORY', 'BUSINESSNAME',
                                                     'SEMANTICKEY'])

        if val == 0:
            # with open("log" + ".txt", "a") as myfile:
            #     myfile.write(singleFile1 + " " + file + " " + "0\n")
             print(singleFile1,file, 0)
        else:
            from_records = list(records.load(dir + singleFile1, ','))
            to_records = list(records.load(dir + file, ','))
            value = getAccruacy(len(from_records), len(to_records), patch.weightList)
            maxsimilarity.append((file, singleFile1, value))
            print(singleFile1,file,value)
            # with open("log" + ".txt", "a") as myfile:
            #     myfile.write(singleFile1 + " " + file + " " + str(value) + "\n")
            added = []
            removed = []
            # '+file.split('.csv
            # ')[0]+'

            with open('Layout_Output/' + singleFile1.replace('.csv', '_') + file.replace('.csv', '.json')) as data_file:
                data = json.load(data_file)
            for each_data in data['added']:
                added.append(each_data['COLUMNNAME'])

            for each_data in data['removed']:
                removed.append(each_data['COLUMNNAME'])

        patch.weightList = []

    showSimilarity(maxsimilarity)

def main():

    console_input=input("Enter 1 for comparing 2 layouts.\nEnter 2 for compaing Single layout with other.\nEnter 3 for comparing all layouts with each other\n")
    #console_input = '1'
    if console_input == '1':
        similarity = runSingle()
        matchLayout(similarity)
    elif console_input == '3':
        with open("log" + ".txt", "a") as myfile:
            myfile.write("#############NEW RUN STARTED#############\n")
        onlyfiles = [f for f in listdir(dir)]
        for file in onlyfiles:
            runAll(file)
    elif console_input == '2':
        runSingleInAll()

    # _diff_and_summarize('CSVdiff/b.csv', 'CSVdiff/a.csv',  index_columns=['FieldName'],
    #                     ignored_columns=['SubLayout', 'Subtype'])

    # added=[]
    # removed=[]
    # with open('output.json') as data_file:
    #     data = json.load(data_file)
    #
    # for each_data in data['added']:
    #     added.append(each_data['COLUMNNAME'])
    #
    # for each_data in data['removed']:
    #     removed.append(each_data['COLUMNNAME'])


main()

