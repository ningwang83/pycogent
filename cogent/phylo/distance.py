#!/usr/bin/env python
"""Estimating pairwise distances between sequences.
"""
from cogent.util import parallel, table, warning
from cogent.maths.stats.util import Numbers
from cogent.core.tree import LoadTree
from cogent import LoadSeqs

from warnings import warn

__author__ = "Gavin Huttley"
__copyright__ = "Copyright 2007, The Cogent Project"
__credits__ = ["Gavin Huttley", "Peter Maxwell", "Matthew Wakefield"]
__license__ = "GPL"
__version__ = "1.0.1"
__maintainer__ = "Gavin Huttley"
__email__ = "gavin.huttley@anu.edu.au"
__status__ = "Production"

class EstimateDistances(object):
    """Base class used for estimating pairwise distances between sequences.
    Can also estimate other parameters from pairs."""
    
    def __init__(self, seqs, submodel, threeway=False, motif_probs = None,
                do_pair_align=False, rigorous_align=False, est_params=None):
        """Arguments:
            - seqs: an Alignment or SeqCollection instance with > 1 sequence
            - submodel: substitution model object Predefined models can
              be imported from cogent.evolve.models
            - threeway: a boolean flag for using threeway comparisons to
              estimate distances. default False. Ignored if do_pair_align is
              True.
            - do_pair_align: if the input sequences are to be pairwise aligned
              first and then the distance will be estimated. A pair HMM based
              on the submodel will be used.
            - rigorous_align: if True the pairwise alignments are actually
              numerically optimised, otherwise the current substitution model
              settings are used. This slows down estimation considerably.
            - est_params: substitution model parameters to save estimates from
              in addition to length (distance)
        
        Note: Unless you know a priori your alignment will be flush ended
        (meaning no sequence has terminal gaps) it is advisable to construct a
        substitution model that recodes gaps. Otherwise the terminal gaps will
        significantly bias the estimation of branch lengths when using
        do_pair_align.
        """
        
        if do_pair_align:
            self.__threeway = False
        else:
            # whether pairwise is to be estimated from 3-way
            self.__threeway = [threeway, False][do_pair_align]
        
        self.__seq_collection = seqs
        self.__seqnames = seqs.getSeqNames()
        self.__motif_probs = motif_probs
        # the following may be pairs or three way combinations
        self.__combination_aligns = None
        self._do_pair_align = do_pair_align
        self._rigorous_align = rigorous_align
        # substitution model stuff
        self.__sm = submodel
        
        # store for the results
        self.__param_ests = {}
        self.__est_params = est_params or []
        
        self.__run = False # a flag indicating whether estimation completed
        # whether we're on the master CPU or not
        self._on_master_cpu = parallel.getCommunicator().rank == 0
    
    def __str__(self):
        return str(self.getTable())
    
    def __make_pairwise_comparison_sets(self):
        comps = []
        names = self.__seq_collection.getSeqNames()
        n = len(names)
        for i in range(0, n - 1):
            for j in range(i + 1, n):
                comps.append((names[i], names[j]))
        return comps
    
    def __make_threeway_comparison_sets(self):
        comps = []
        names = self.__seq_collection.getSeqNames()
        n = len(names)
        for i in range(0, n - 2):
            for j in range(i + 1, n - 1):
                for k in range(j + 1, n):
                    comps.append((names[i], names[j], names[k]))
        return comps
    
    def __make_pair_alignment(self, seqs, show_progress, opt_kwargs):
        if show_progress:
            print "\tPairwise aligning: %s" % \
                        " <-> ".join(seqs.NamedSeqs.keys())
        lf = self.__sm.makeLikelihoodFunction(\
                    LoadTree(tip_names=seqs.getSeqNames()),
                    aligned=False)
        lf.setSequences(seqs.NamedSeqs)
        if self._rigorous_align:
            lf.optimise(**opt_kwargs)
        lnL = lf.getLogLikelihood()
        (vtLnL, aln) = lnL.edge.getViterbiScoreAndAlignment()
        return aln
    
    def __doset(self, sequence_names, show_progress, dist_opt_args,
                    aln_opt_args):
        # slice the alignment
        seqs = self.__seq_collection.takeSeqs(sequence_names)
        if self._do_pair_align:
            align = self.__make_pair_alignment(seqs, show_progress,
                                                aln_opt_args)
        else:
            align = seqs
        # note that we may want to consider removing the redundant gaps
        
        # create the tree object
        tree = LoadTree(tip_names = sequence_names)
        
        # make the parameter controller
        lf = self.__sm.makeLikelihoodFunction(tree)
        if not self.__threeway:
            lf.setParamRule('length', is_independent = False)
        
        if self.__motif_probs:
            lf.setMotifProbs(self.__motif_probs)
        
        # we probably want to make all pars local, but for time being ..
        lf.setAlignment(align)
        if dist_opt_args['show_progress']:
            print "\tEstimating distance:"
        lf.optimise(**dist_opt_args)
        
        if dist_opt_args['show_progress']:
            print lf
        
        # get the statistics
        stats_dict = lf.getStatisticsAsDict()
        
        # if two-way, grab first distance only
        if not self.__threeway:
            self.__param_ests[sequence_names] = \
                {'length': stats_dict['length'].values()[0] * 2.0}
        else:
            self.__param_ests[sequence_names] = {'length': stats_dict['length']}
        
        # include any other params requested
        for param in self.__est_params:
            self.__param_ests[sequence_names][param] = \
                        stats_dict[param].values()[0]
    
    def run(self, show_progress = False, dist_opt_args=None, aln_opt_args=None,
            progress_interval = 1, **kwargs):
        """Start estimating the distances between sequences. Distance estimation
        is done using the Powell local optimiser. This can be changed using the
        dist_opt_args and aln_opt_args.
        
        Arguments:
            - show_progress: whether to display progress. More detailed progress
              information from individual optimisation is controlled by the
              ..opt_args.
            - dist_opt_args, aln_opt_args: arguments for the optimise method for
              the distance estimation and alignment estimation respectively.
            - progress_interval: progress reported every # pairs done"""
        
        if 'local' in kwargs:
              warn("local argument ignored, provide it to dist_opt_args or"\
              " aln_opt_args", DeprecationWarning, stacklevel=2)
        
        dist_opt_args = dist_opt_args or {}
        aln_opt_args = aln_opt_args or {}
        # set the optimiser and progress defaults
        dist_opt_args['show_progress'] = dist_opt_args.get('show_progress',
                                            False)
        aln_opt_args['show_progress'] = aln_opt_args.get('show_progress', False)
        dist_opt_args['local'] = dist_opt_args.get('local', True)
        aln_opt_args['local'] = aln_opt_args.get('local', True)
        # generate the list of unique sequence sets (pairs or triples) to be
        # analysed
        if self.__threeway:
            combination_aligns = self.__make_threeway_comparison_sets()
        else:
            combination_aligns = self.__make_pairwise_comparison_sets()
        
        (parallel_context, parallel_subcontext) = \
                parallel.getSplitCommunicators(len(combination_aligns))
        
        count_progress = 0
        for _round in range((len(combination_aligns)-1)/\
                            parallel_context.size +1):
            i = _round * parallel_context.size + parallel_context.rank
            if i >= len(combination_aligns):
                local_value = None
            else:
                comp = combination_aligns[i]
                parallel.push(parallel_subcontext)
                try:
                    count_progress += 1
                    if count_progress % progress_interval == 0 and\
                            show_progress:
                        print 'Doing [%s/%s]: %s' % \
                            (i+1, len(combination_aligns), ' <-> '.join(comp))
                    self.__doset(comp, show_progress, dist_opt_args,
                                aln_opt_args)
                finally:
                    # back up to analysis level
                    parallel.pop(parallel_subcontext)
                local_value = self.__param_ests[comp]
            
            for cpu in range(parallel_context.size):
                i = _round * parallel_context.size + cpu
                if i >= len(combination_aligns):
                    continue
                comp = combination_aligns[i]
                value = parallel_context.broadcastObj(local_value, cpu)
                self.__param_ests[comp] = value
    
    def getPairwiseParam(self, param, summary_function="mean"):
        """Return the pairwise statistic estimates as a dictionary keyed by
        (seq1, seq2)
        
        Arguments:
            - param: name of a parameter in est_params or 'length'
            - summary_function: a string naming the function used for
              estimating param from threeway distances. Valid values are 'mean'
              (default) and 'median'."""
        summary_func = summary_function.capitalize()
        pairwise_stats = {}
        assert param in self.__est_params + ['length'], \
                "unrecognised param %s" % param
        if self.__threeway and param == 'length':
            pairwise = self.__make_pairwise_comparison_sets()
            # get all the distances involving this pair
            for a, b in pairwise:
                values = Numbers()
                for comp_names, param_vals in self.__param_ests.items():
                    if a in comp_names and b in comp_names:
                        values.append(param_vals[param][a] + \
                                    param_vals[param][b])
                
                pairwise_stats[(a,b)] = getattr(values, summary_func)
        else:
            # no additional processing of the distances is required
            
            for comp_names, param_vals in self.__param_ests.items():
                pairwise_stats[comp_names] = param_vals[param]
            
        return pairwise_stats
    
    def getPairwiseDistances(self,summary_function="mean", **kwargs):
        """Return the pairwise distances as a dictionary keyed by (seq1, seq2).
        Convenience interface to getPairwiseParam.
        
        Arguments:
            - summary_function: a string naming the function used for
              estimating param from threeway distances. Valid values are 'mean'
              (default) and 'median'.
        """
        return self.getPairwiseParam('length',summary_function=summary_function,
                                    **kwargs)
    
    def getParamValues(self, param, **kwargs):
        """Returns a Numbers object with all estimated values of param.
        
        Arguments:
            - param: name of a parameter in est_params or 'length'
            - **kwargs: arguments passed to getPairwiseParam"""
        ests = self.getPairwiseParam(param, **kwargs)
        return Numbers(ests.values())
    
    def getTable(self,summary_function="mean", **kwargs):
        """returns a Table instance of the distance matrix.
        
        Arguments:
            - summary_function: a string naming the function used for
              estimating param from threeway distances. Valid values are 'mean'
              (default) and 'median'."""
        d = \
         self.getPairwiseDistances(summary_function=summary_function,**kwargs)
        if not d:
            d = {}
            for s1 in self.__seqnames:
                for s2 in self.__seqnames:
                    if s1 == s2:
                        continue
                    else:
                        d[(s1,s2)] = 'Not Done'
        twoD = []
        for s1 in self.__seqnames:
            row = [s1]
            for s2 in self.__seqnames:
                if s1 == s2:
                    row.append('')
                    continue
                try:
                    row.append(d[(s1,s2)])
                except KeyError:
                    row.append(d[(s2,s1)])
            twoD.append(row)
        T = table.Table(['Seq1 \ Seq2'] + self.__seqnames, twoD, row_ids = True,
                        missing_data = "*")
        return T
    
    def getNewickTrees(self):
        """Returns a list of Newick format trees for supertree methods."""
        trees = []
        for comp_names, param_vals in self.__param_ests.items():
            tips = []
            for name in comp_names:
                tips.append(repr(name)+":%s" % param_vals[name])
            trees.append("("+",".join(tips)+");")
        
        return trees
    
    def writeToFile(self, filename, summary_function="mean", format='phylip',
            **kwargs):
        """Save the pairwise distances to a file using phylip format. Other
        formats can be obtained by getting to a Table.  If running in parallel,
        the master CPU writes out.
        
        Arguments:
            - filename: where distances will be written, required.
            - summary_function: a string naming the function used for
              estimating param from threeway distances. Valid values are 'mean'
              (default) and 'median'.
            - format: output format of distance matrix
        """
        
        if not self._on_master_cpu:
            return None # we only write output from 0th node
        
        table = self.getTable(summary_function=summary_function, **kwargs)
        
        outfile = open(filename, 'w')
        outfile.write(table.tostring(format = format))
        outfile.close()
        
        return
    