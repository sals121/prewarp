NIST Data Publication:
AM Bench 2022 3D Build Modeling Challenge Description Data (AMB2022-01)
Version 1.0.0
DOI: https://doi.org/10.18434/mds2-2607

Authors:
  Brandon Lane
    National Institute of Standards and Technology
    Intelligent Systems Division
  Lyle  Levine
    National Institute of Standards and Technology
     Materials Science and Engineering Division
  David Deisenroth
    National Institute of Standards and Technology
    Intelligent Systems Division
  Ho Yeung
    National Institute of Standards and Technology
    Intelligent Systems Division
  Vipin  Tondare
    National Institute of Standards and Technology
    Intelligent Systems Division
  Sergey  Mekhontsev
    National Institute of Standards and Technology
    Intelligent Systems Division
  Jorge  Neira
    National Institute of Standards and Technology
    Intelligent Systems Division

Contact:
  Brandon Lane
    brandon.lane@nist.gov

Description:

The following data files are provided in support of the AM Bench 2022 modeling
challenges associated with 3D metal builds, performed on the NIST Additive
Manufacturing Metrology Testbed (AMB2022-01).  Description of the associated
measurements and model are provided on the AMB2022-01 challenge description
webpage (https://www.nist.gov/ambench/amb2022-01-benchmark-measurements-and-challenge-problems).

--------------
Data Use Notes
--------------

This data is publicly available according to the NIST statements of
copyright, fair use and licensing; see
https://www.nist.gov/director/copyright-fair-use-and-licensing-statements-srd-data-and-software

You may cite the use of this data as follows:
Lane, Brandon, Levine, Lyle, Deisenroth, David, Yeung, Ho, Tondare, Vipin,
Mekhontsev, Sergey, Neira, Jorge (2022), AM Bench 2022 3D Build Modeling
Challenge Description Data (AMB2022-01), Version 1.0.0, National Institute of
Standards and Technology, https://doi.org/10.18434/mds2-2607 (Accessed: [give
download date])

--------------
Disclaimer
--------------

The National Institute of Standards and Technology (NIST) uses its best efforts to deliver high-quality copies of the AM Bench database and to verify that the data contained therein have been selected on the basis of sound scientific judgment. However, NIST makes no warranties to that effect, and NIST shall not be liable for any damage that may result from errors or omissions in the AM Bench databases.

Certain commercial equipment, instruments, or materials are identified in this paper in order to specify the experimental procedure adequately.  Such identification is not intended to imply recommendation or endorsement by NIST, nor is it intended to imply that the materials or equipment identified are necessarily the best available for the purpose.

---------------
Version History
---------------

1.0.0 (this version). 
  Initial release.

--------------------------
Methodological Information
--------------------------

CAD_Geometry:
	The AMB2022-01-AMMT 3D build geometry was designed in Solidworks 2021 computer-aided design (CAD) software.  Open-source formats of the associated parts and assemblies were exported from Solidworks in to either stereolithography (STL) or STEP 214 file types. These include the individual bridge structure parts, the recoater guide parts, and an assembly of all 3D-printed parts in their respective placement locations on the 100 mm X 100 mm build plate.   


Scan_Strategy:
	The '/Scan_Strategy' directory contains two files: an HDF5 containing the digital commands send to the additive manufacturing metrology testbed (AMMT) controller to execute the laser/galvo system controls and synchronized instrument triggering, and a Matlab m-file script providing examples on how to access and plot the scan strategy data in real-world coordinates.  Note that the HDF5 files are not the actual files used to control the AMMT, which are a set of individual comma separated value (CSV) files containing American Standard Code for Information Interchange (ASCII) text values of the AMMT commands.  The HDF5 format offers several advantages over CSV for use by external users (https://www.hdfgroup.org/solutions/hdf5/).  The scan strategy is designed using combination of NIST-developed code for auto-generating scan strategy from STL geometry (called 'SimpleAM'), and manual scripting (e.g., for the 'thin wall' members in the hollow leg).  For details on the methods used to construct the scan strategy, refer to Yeung et al. 2021 (https://doi.org/10.26153/tsw/17660).  The HDF5 was constructed using Matlab 2021a HDF5 toolbox by converting original ASCII-text based CSV files.   
	
	The HDF5 scan strategy file is composed of the following group structure, attributes, and datasets:

	Group '/AMB2022-01-AMMT' :  Top-level group with names based on the corresponding build identifier (BuildID).
    		Attributes:
       		 'HDF5_file_datetime':  Date and time the HDF5 file was constructed
       		 'XYPT_file_datetime':  Date and time the original digital command files were constructed
       		 'Notes':  User-inputted notes during construction of the HDF5 file.
       		 'layerthickness':  Layer thickness of the 3D build, or physical space between layers in the /XYPT/N/ groups 
       		 'layerthickness_units':  String indicating units of 'layerthickness' attribute

	Group '/Calibration/' : Group containing attributes and datasets associated with any calibration or error correction methods applied to the main X,Y,P, and T vectors data.
    		Attributes:
       		 'X_units':  String indicating units of 'X' vectors
       		 'Y_units':  String indicating units of 'Y' vectors
       		 'P_units':  String indicating units of 'P' vectors
        		 'GalvoCal_Applied':  Boolean indicating if X,Y values in the /XYPT/N/ groups have error-correction applied
       		 'GalvoCal_Date':  Date of galvo calibration 
     		 'GalvoCal_X_poly':  Vector of polynomial coefficients of X position correction.  Input is commanded X, output is corrected X.    
       		 'GalvoCal_Y_poly':  Vector of polynomial coefficients of X position correction.  Input is commanded Y, output is corrected Y.
       		 'LaserCal_Applied':  Boolean indicating if P values in the /XYPT/N/ groups have error-correction applied
       		 'LaserCal_poly':  Vector of polynomial coefficients of laser power P correction.  Input is commanded P, output is corrected P. 
	
	Group '/XYPT/' : Group containing the main AMMT digital commanded galvo position, laser power, instrument triggers.
		Attributes:
		 'Trigger_bit0': String name of instrument triggered by bit 0
		 'Trigger_bit1': String name of instrument triggered by bit 1
		 'Trigger_bit2': String name of instrument triggered by bit 2
		 'Trigger_bit3': String name of instrument triggered by bit 3
		 'digital_rate': The digital sampling rate of the X,Y,P, and T vectors. The inverse of digital_rate is the time period between each element in X,Y,P, and T vectors.
		 'digital_rate_units': String indicating units of 'digital_rate'
		Groups '/XYPT/N' : Multiple group names where 'N' indicates the layer number. 
			Attributes: n/a
    			Dataset 'P': nx1 vector of numbers indicating the point-by-point commanded layer power 
    			Dataset 'T' : nx1 vector of numbers containing the instrument trigger command as a single unsigned integer (see description above);
    			Dataset 'X': nx1 vector of numbers indicating the point-by-point commanded galvo X position 
    			Dataset 'Y': nx1 vector of numbers indicating the point-by-point commanded galvo Y position 

	The '/XYPT/N/T' datasets, or the 'trigger' vector, representing the instrument trigger is an integer value of either 0, 2, 4, or 6.  In binary number form (e.g., 0110 = 6), each bit of these numbers represents the execution of an external trigger event for a particular instrument.  The coaxial melt pool camera data is not used for the AMB2022-01 challenges, but will be described in future publications and available in future datasets.  The array indices of the ‘T’ data correspond exactly to those in the ‘X’, ‘Y’, or ‘P’ arrays, and thus provides synchronization between camera image frame capture and the laser scan paths. 

Materials:	
	The /Materials/ directory contains vendor supplied specification sheets for the IN718 metal powder used in the AMB2022-01 3D builds (AMB2022-01_PowderMillSpecSheet.pdf), which includes powder morphology measurements and chemical composition.  Additionally, the /Materials/PowderSizeDistribution/ directory contains NIST-measured powder size distribution (PSD) results using methods described in Whiting et. al. (https://doi.org/10.1016/j.cirp.2019.04.075).  Several sub-directories are named based on (nonconsecutive) test number, where some invalid tests were omitted. These also contain report data exported from the PSD instrument software in the form of ASCII text files with *.xle extension. Variables and parameters listed in the *.xle report files are described in the included 'Camsizer_PowderCharacteristicsDefinitions.pdf' document provided by the instrument vendor.    

Thermocouples:
	Three CSV files are contained in the /Thermocouples/ directory; one each for build 6, 7, and 8.  These include columnar data representing timeseries measurements from three thermocouples:  two type-K thermocouples  mounted under the IN718 build plate at approximately the (-12.7 mm, -12.7 mm) position under Part 3 (column named 'P3') and (-12.7 mm, 1.7 mm) position under Part 2 (column named 'P2'), and a third thermocouple was suspended above the build area within the chamber (column named 'Chamber').  The first column in each file is time (column named 'Time') in HH:MM:SS format.

ChallengeSubmissionTemplates:
	This directory contains templates for modelers to use to enter their model results data and submit for the various AM-bench modeling challenges.  These templates are CSV, or other delimited (e.g., tab) ASCII text formatted tables.  Not all challenges will have a template available in this directory, and modelers will need to read the associated challenge descriptions on the AM-Bench website for direction on what format to submit results.


-------------
Data Manifest
-------------

2607_README.txt : This readme file.

/CAD_Geometry/ : Directory containing data described in Section 2.1 of the AMB2022-01 Challenge Description, which includes various CAD-generated files of the as-designed 3D build part geometries. 

	- 	AMB2022-01-AMMT-PlateLayoutAssy.STL: Stereolithography file of the of the four bridge parts and two recoater guide parts placed on the approximate, as-designed locations on the build substrate.  
	- 	AMB2022-01-AMMT-PlateLayoutAssy.STEP: STEP file of the of the four bridge parts and two recoater guide parts placed on the approximate, as-designed locations on the build substrate.
	-	AMB2022-01-AMMT-PartCAD.STL : Stereolithography file representing the external and internal geometry of and individual bridge-structure part(s), including the thin wall sections in Leg 10. 
	-	AMB2022-01-AMMT-PartCAD.STEP : STEP file representing the external and internal geometry of and individual bridge-structure part(s), including the thin wall sections in Leg 10.
	-	AMB2022-01-AMMT-RecoaterGuideCAD.STL: Stereolithography file representing the recoater guides’ geometry (G1 and G2) 
	-	AMB2022-01-AMMT-RecoaterGuideCAD.STL : STEP file representing the recoater guides’ geometry (G1 and G2) 

/Scan_Strategy/ : Directory containing the point-by-point commanded scan strategy of the AMB2022-01 3D builds performed on the additive manufacturing metrology testbed.

	- 	AMB2022-01-AMMT-XYPT_v1.h5 : HDF5 file containing the point-by-point laser scan strategy for the entire AMB2022-01 3D build.  See Methodological Information section above for detailed information on the file structure.
	-	AMB2022-01-XYPT-ExampleMatlabPlots.m : Matlab m-file script with multiple examples generating plots of the scan strategy directly from the HDF5 file.

/Materials/  : Directory containing material characterization data pertaining to the IN718 metal powder and/or any build plate material

	-	AMB2022-01_PowderMillSpecSheet.pdf.
	/PowderSizeDistribution/
		This directory containts various results from the powder size distribution tests performed at NIST on the IN718 powder.
		-	Camsizer_PowderCharacteristicsDefinitions.pdf : Document provided by the powder-size distribution instrument detailing various powder particle geometric parameters output by the instrument report
		/textX/
			Directory, with X being the test number of four repeated measurements, X = 1,2,4 & 5
			-	IN718_testX_x_area_836.xle : ASCII text file report from the powder distribution measurement, including statistics and size distribution for the 'x_area' geometric parameter
			-	IN718_testX_xc_min_836.xle : ASCII text file report from the powder distribution measurement, including statistics and size distribution for the 'xc_min' geometric parameter
			-	IN718_testX_xc_min_836.xle : ASCII text file report from the powder distribution measurement, including statistics and size distribution for the 'xFemax' geometric parameter

/Thermocouples/ : This directory containing timeseries measurement results from in-situ thermocouples during 3D builds. 

	-	AMB2022-01-AMMT-BX-Thermocouple.csv : CSV text file including columnar timeseries data of thermocouple measurements performed during the 'Xth' 3D build (X = 6, 7, 8)

/ChallengeSubmissionTemplates/ : This directory contains challenge submission templates in CSV form for modelers to use when submitting modeling results.

	-	CHAL-AMB2022-01-MS submission template.csv - challenge submission template for the 'Microstructure' challenge
	-	CHAL-AMB2022-01-PE submission template.csv - challenge submission template for the  'Phase Evolution' challenge
	-	CHAL-AMB2022-01-RS submission template.csv - challenge submission template for the 'Residual Elastic Strain' challenge
	-	CHAL-AMB2022-01-SCR submission template.csv - challenge submission template for the 'Solid Cooling Rate' challenge
	-	CHAL-AMB2022-01-TAM submission template.csv - challenge submission template for the 'Time Above Melting' challenge



