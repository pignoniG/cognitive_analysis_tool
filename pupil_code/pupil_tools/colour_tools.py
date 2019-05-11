
from bisect import bisect_left
import csv
from scipy.signal import savgol_filter
import numpy as np
from datetime import *


def effectiveCornealFluxDensity(L,a,e):
	# Ported from R to python, originally written by Jose Gama (CVD) https://rdrr.io/rforge/CVD/man/
	# effective Corneal Flux Density = product of luminance, area, and the monocular effect, F = Lae
	# L=luminance, a = field diameter in de, e = number of eyes (1 or 2)
	# Watson A. B., Yellott J. I. (2012). A unified formula for light-adapted pupil size. Journal of Vision, 12(10):12, 1–16. http://journalofvision.org/12/10/12/, doi:10.1167/5.9.6.
	return L*a*attenuationNumberOfEyes(e)



def lightAdaptedPupilSizeWatsonAndYellott(L, a, y, y0, e):
	# Ported from R to python, originally written by Jose Gama (CVD) https://rdrr.io/rforge/CVD/man/
	# pupil diameter ranges Watson & Yellott 2012
	# L=luminance in cd m^-2, a = field diameter in deg, y = age in years, y0 = reference age, e = number of eyes (1 or 2)
	# Watson A. B., Yellott J. I. (2012). A unified formula for light-adapted pupil size. Journal of Vision, 12(10):12, 1–16. http://journalofvision.org/12/10/12/, doi:10.1167/5.9.6.
	F = effectiveCornealFluxDensity(L,a,e)
	Dsd = lightAdaptedPupilSizeStanleyAndDavies(F,1)
	ps=Dsd+(y-y0)*(0.02132 - 0.009562*Dsd)
	return ps

def lightAdaptedPupilSizeStanleyAndDavies(L, a):
	# Ported from R to python, originally written by Jose Gama (CVD) https://rdrr.io/rforge/CVD/man/
	# pupil diameter ranges Stanley and Davies 1995
	# L=luminance in cd m^-2, a = field diameter in de
	# Watson A. B., Yellott J. I. (2012). A unified formula for light-adapted pupil size. Journal of Vision, 12(10):12, 1–16. http://journalofvision.org/12/10/12/, doi:10.1167/5.9.6.
	# Stanley, P. A., & Davies, A. K. (1995). The effect of field of view size on steady-state pupil diameter. Ophthalmic & Physiological Optics, 15(6), 601–603.
	return (7.75 - 5.75*((L*a/846)**0.41/((L*a/846)**0.41+2)))

def attenuationNumberOfEyes(e):
	# Ported from R to python, originally written by Jose Gama (CVD) https://rdrr.io/rforge/CVD/man/
	# attenuation as a function M(e) of number of eyes e (1 or 2)
	# M(1) = 0.1, M(2) = 1, otherwise 0
	# Watson A. B., Yellott J. I. (2012). A unified formula for light-adapted pupil size. Journal of Vision, 12(10):12, 1–16. http://journalofvision.org/12/10/12/, doi:10.1167/5.9.6.
	if (e==1): e=0.1
	elif (e==2): e=1
	else: e=0
	return e

def calcPupil(l,y,y0,e,a ):
	# calculate the pupil size for a list (l) of luminance values includes the parameters for the "lightAdaptedPupilSizeWatsonAndYellott" function
	# luminanceValue=luminance in cd m^-2, a = field diameter in de, y = age in years, y0 = reference age, e = number of eyes (1 or 2)
	
	pupilSizes=[]
	for luminanceValue in l:
		pupilSize = lightAdaptedPupilSizeWatsonAndYellott(luminanceValue , a, y, y0, e)
		pupilSizes.append(pupilSize)

	return (pupilSizes)


def lightPupillaryResponseMoonAndSpencer(L):

	#an alternative Pupillary response equation

	Lb=L/3.183098861838

	D = 4.9 - 3 * np.tanh(0.4*(np.log10( Lb ) - 0.5) )
	return D

def linearRelation(x,x1, y1, x2, y2):

	y = (x -x1)*(y2 -y1)/(x2 -x1)+y1
	return y


def parabolicRelation(x, x1, y1, x2, y2, x3, y3):

	# Linear equations system
	a = np.array([[x1**2,x1,1], [x2**2,x2,1], [x3**2,x3,1]])
	b = np.array([y1,y2,y3])
	E = np.linalg.solve(a, b)

	# from matrix to float
	m = float(E[0])
	n = float(E[1])
	o = float(E[2])

	# Implicit values
	yEq = m* x**2 + n*x + o
	return yEq








def relativeLuminanceClac(R,G,B):

	# First converts the gamma-compressed RGB values to linear RGB
	# and then applies the luminosity function
	# Y=0.2126R+0.7152G+0.0722B
	# to obtain the "Relative luminance" 0 - 1 from rgb values 0-255 

	# formula ported from WCAG specifications https://www.w3.org/TR/WCAG21/#dfn-relative-luminance

	gamma=2.4

	R=R/255
	G=G/255
	B=B/255
	if (R <= 0.03928):
	    R = R /12.92 
	else:
	    R = ((R +0.055)/1.055)**gamma
	if (G <= 0.03928):
	    G = G /12.92 
	else:
	    G = ((G +0.055)/1.055)**gamma

	if (B <= 0.03928):
	    B = B /12.92 
	else:
	    B = ((B +0.055)/1.055)**gamma
	L = 0.2126 * R + 0.7152 * G + 0.0722 * B 

	return L


def inverserelativeLuminanceClac(L):
	# inverse of the luminosity function 
	# from "Relative luminance" 0 - 1 to gray-scale 0-255 

	
	gamma=2.4

	X = L
	if (X <= 0.11784/12.92):
	    X = X *12.92 
	else:
	    X =X**(1/gamma)	    
	    X= (X*1.055)-0.055     
	X=X*255
	return X

