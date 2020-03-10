"""
 This code compares 4 different approaches for signal declipping:

 - solvers.IHT_inpainting discards the clipped samples and performs sparse decomposition 
     on the unclipped samples, using IHT and a fixed DCT dictionary
 - solvers.DictionaryLearning_inpainting discards the clipped samples and performs a 
     gradient descent-based dictionary learning on the unclipped samples
 - solvers.consistentIHT performs consistent IHT for declipping, using a fixed DCT
 dictionary [1]
 - solvers.consistentDictionaryLearning performs consistent dictionary learning for
 signal declipping, as proposed in [2]


 References:
 [1]: Consistent iterative hard thresholding for signal declipping, 
     S. Kitic, L. Jacques, N. Madhu, M. P. Hopwood, A. Spriet, C. De Vleeschouwer, ICASSP, 2013
 
 [2]: Consistent dictionary learning for signal declipping, 
     L. Rencker, F. Bach, W. Wang, M. D. Plumbley,
     Latent Variable Analysis and Signal Separation (LVA/ICA), Guildford, UK, 2018
 
 --------------------- 

 Author: Lucas Rencker
         Centre for Vision, Speech and Signal Processing (CVSSP), University of Surrey

 Contact: lucas.rencker@surrey.ac.uk
                    
 Last update: 01/05/18
 
 This code is distributed under the terms of the GNU Public License version 3 
 (http://www.gnu.org/licenses/gpl.txt).
"""                

import numpy as np
import matplotlib.pyplot as plt
import scipy.io.wavfile
from pupil_code.dict_learning_tools import solvers
from pupil_code.dict_learning_tools import utils as u

from pupil_code.pupil_tools import data_tools
import csv
from os.path import join
#import importlib
#importlib.reload(solvers)
#importlib.reload(u)

plt.close('all')

#%% Parameters

param = {}
param["N"] =12 # size of frames
param["hop"] = 0.25*param["N"]  # hop size
param["redundancyFactor"] = 2  # redundancy of dictionary
param["M"] = param["N"] * param["redundancyFactor"]  # number of atoms
param["wa"] = u.wHamm  # analysis window
param["ws"] = param["wa"]  # synthesis window

M = param["M"]

#%% Generate DCT dictionary:

D_DCT = u.DCT_dictionary(param)

#%% Read signal


data_source = '/Volumes/SSD 2TB /20200324_Bergen_experiment /recordings/NAV/N1'

indexLum, timeStampsLum, avgLum, spotLum, fieldDiameters = data_tools.readCamera(data_source)


x = np.array(spotLum)

x = x/np.max(abs(x))  # normalize signal

# plt.plot(x)

#%% Clip signal:

y=x


 
#%% Decompose signal into overlapping time-frames:

Y = u.signal2frames(x,param)
Nframes = Y.shape[1]

# crop signals:
L = int((Nframes-1)*param["hop"]+param["N"])
y = y[:L]
x = x[:L]

#%% Detect reliable samples:

# Detect clipping level:
ClippingLevel = max(abs(y))

reliable_samples = np.logical_and(y<ClippingLevel,y>-ClippingLevel)
reliable_samples_mat = u.binary_vec2mat(reliable_samples,param)

clipped_samples = np.logical_not(reliable_samples)
clipped_samples_mat = np.logical_not(reliable_samples_mat)

SNRin_clipped = u.SNR(x[clipped_samples],y[clipped_samples])

print('%.1f percent of clipped samples' % (sum(1*clipped_samples)/x.size*100))

#%% Reconstruct signal using IHT for inpainting:

print('Proposed consistent dictionary learning:')

# DL parameters:
paramDL={}
paramDL["K"] = 32 
paramDL["Nit"] = 50 # number of iterations
paramDL["Nit_sparse_coding"] = 20 # number of iterations sparse coding step
paramDL["Nit_dict_update"] = 20 # number of iterations dictionary update step
paramDL["warm_start"] = 1 # 1 to perform warm start at each iteration
paramDL["A_init"] = np.zeros((M,Nframes)) # initialize sparse coefficient matrix
paramDL["D_init"] = D_DCT # initialize dictionary
paramDL["loud"] = 1 # print results

D_consDL, A, cost = solvers.consistentDictionaryLearning(Y,clipped_samples_mat,paramDL)

X_est_consDL = D_consDL@A
x_est_consDL = u.frames2signal(X_est_consDL,param)

#plt.figure()
#plt.plot(np.log(cost))
#plt.title('Objective')

SNRout_consDL = u.SNR(x,x_est_consDL)
SNRout_clipped = u.SNR(x[clipped_samples],x_est_consDL[clipped_samples])

print('SNRout: %.3f dB' % SNRout_consDL)
print('SNR clipped improvement: %.3f dB' % (SNRout_clipped-SNRin_clipped))

plt.figure()
plt.plot(x,color="blue", linewidth=1.0, linestyle="-", label="clean")
plt.plot(x_est_consDL,color="red", linewidth=1.0, linestyle="-", label="estimate")
plt.plot(y,color="green", linewidth=1.0, linestyle="--", label="clipped")
plt.xlim(0, L)
plt.legend()
plt.title("Consistent DL: SNR = %.2f dB" % SNRout_consDL)
plt.tight_layout()

#%% Plots

# "zoom-in" to particular area:
samples = np.arange(46800,46900) 

# percentage of missing samples:
# sum(~reliable_samples(samples))/length(samples)*100

f, axarr = plt.subplots(2, 2)
axarr[1, 1].plot(samples, x[samples], label="clean")
axarr[1, 1].plot(samples, x_est_consDL[samples], label="estimate")
axarr[1, 1].plot(samples, y[samples], label="clipped")
axarr[1, 1].set_title(('Consistent dictionary learning: SNR = %.2f dB' % SNRout_consDL))
axarr[1, 1].legend()
plt.tight_layout()

plt.show()





#%% Save results
 
print("saving to CSV...")

first_row = True
row = ["SpotLum_declip"]

with open(join(data_source, 'outputFromVideo_declip.csv'), 'w') as csvFile:
    writer = csv.writer(csvFile)
    if first_row:
        writer.writerow(row)
        first_row = False

    for lum in list(x_est_consDL):

        
        writer.writerow([lum]) 

print("saved to CSV!")
